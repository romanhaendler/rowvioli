"""`rowvioli work`, the order of loading, both limits, `max_seconds`, SIGTERM and an unreachable target
(spec tests 9, 10, 11, 13, 14, 19)."""
import re
import signal
import time

import pytest
from conftest import _query, until
from test_run import apply, ok, run


# a source view that takes `seconds` per row, to hold a run while it fills the staging table
SLOW = """create function slow(g int, seconds float) returns int language plpgsql
          as $$ begin perform pg_sleep(seconds); return g; end $$"""


def slow(rv, name, rows, seconds):
    rv.source(f"create view {name} as select slow(g, {seconds}) as id from generate_series(1, {rows}) g")


def source(rv, name, settings, tables):
    return f"""
[{name}]
type = "postgres"
max_age = "1h"
{settings}
[{name}.connection]
url = "{rv.source_url}"
[{name}.tables]
{tables}"""


@pytest.fixture
def ready(rv):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    rv.source(SLOW)
    return rv


def test_a_run_that_exceeds_max_seconds_is_ended_and_the_status_shows_why(ready):
    slow(ready, "hanging", 30, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2", '"public.hanging" = { key = ["id"] }'))
    start = time.monotonic()
    code, answer = run(ready)
    assert time.monotonic() - start < 15
    assert code == 1
    failed = answer["tables"]["raw_erp.hanging"]
    assert failed["status"] == "failed" and "max_seconds" in failed["reason"]
    assert ready.target("select status, attempts, reason = %s from _rowvioli.status",
                        [failed["reason"]]) == [("failed", 1, True)]
    assert ready.target("select status, reason = %s, finished_at is not null from _rowvioli.runs",
                        [failed["reason"]]) == [("failed", True, True)]
    assert ready.target("select to_regclass('raw_erp.hanging')") == [(None,)]


def test_one_slot_loads_the_tables_in_the_order_of_how_far_they_miss_their_maximum_age(ready):
    for name in ("a", "b", "c"):
        ready.source(f"create table {name} (id int primary key)")
        ready.source(f"insert into {name} values (1)")
    apply(ready, source(ready, "erp", "parallel = 3", '"public.a" = { key = ["id"] }\n'
                        '"public.b" = { key = ["id"], max_age = "10m" }\n"public.c" = { key = ["id"] }'))
    ok(ready)
    # a misses 1h by 1h (1x), b misses 10m by 20m (2x), c misses 1h by 30m (0.5x)
    for name, loaded in (("a", "2 hours"), ("b", "30 minutes"), ("c", "90 minutes")):
        ready.target("update _rowvioli.tables set loaded_at = now() - %s::interval where source_table = %s",
                     [loaded, f"public.{name}"])
    first = ready.target("select max(run) from _rowvioli.runs")[0][0]
    ok(ready, "--slots", "1")
    assert ready.target("select t.source_table from _rowvioli.runs r join _rowvioli.tables t on t.id = r.table "
                        "where r.run > %s order by r.run", [first]) == [("public.b",), ("public.a",), ("public.c",)]


HELD = """select s.name, count(*) from pg_locks l join _rowvioli.sources s on s.id = l.classid::int
           where l.locktype = 'advisory' and l.objsubid = 2 and l.granted and l.classid <> 0
             and l.database = (select oid from pg_database where datname = current_database()) group by s.name"""


def test_several_workers_never_exceed_parallel_per_source_nor_max_running_in_total(ready):
    tables = "\n".join(f'"public.slow{i}" = {{ key = ["id"] }}' for i in range(10))
    for i in range(10):
        slow(ready, f"slow{i}", 4, 0.1)
    apply(ready, source(ready, "erp", "parallel = 2", tables) + source(ready, "crm", "parallel = 3", tables))
    ready.target("update _rowvioli.meta set max_running = 4")
    for _ in range(6):
        ready.start("work", "--slots", "4")
    highest, deadline = {"erp": 0, "crm": 0, "total": 0}, time.monotonic() + 60
    # probe pg_locks every 20 ms until every table was loaded once (experiment 5)
    while ready.target("select count(*) from _rowvioli.status where status <> 'ok'") != [(0,)]:
        assert time.monotonic() < deadline
        held = dict(ready.target(HELD))
        for name, n in [*held.items(), ("total", sum(held.values()))]:
            highest[name] = max(highest[name], n)
        time.sleep(0.02)
    # erp's parallel and max_running were reached, so the probe could have seen them broken
    assert highest["erp"] == 2 and highest["crm"] <= 3 and highest["total"] == 4


def test_run_ends_with_1_when_a_run_process_dies_before_claiming(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    ready.target("alter table _rowvioli.runs add constraint broken check (false) not valid")  # the claim fails
    r = ready.run("run", timeout=20)
    assert r.returncode == 1
    assert ready.target("select status from _rowvioli.status") == [("new",)]


def test_a_tables_max_seconds_overrides_the_sources(ready):
    slow(ready, "patient", 3, 1)
    slow(ready, "hasty", 3, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2\nparallel = 2",
                        '"public.patient" = { key = ["id"], max_seconds = 30 }\n"public.hasty" = { key = ["id"] }'))
    code, answer = run(ready)
    assert answer["tables"]["raw_erp.patient"]["status"] == "ok"
    assert "max_seconds" in answer["tables"]["raw_erp.hasty"]["reason"]


def test_work_on_sigterm_lets_the_run_publish_starts_nothing_new_and_exits_0(ready):
    slow(ready, "first", 3, 1)
    slow(ready, "second", 3, 1)
    apply(ready, source(ready, "erp", "", '"public.first" = { key = ["id"] }\n"public.second" = { key = ["id"] }'))
    worker = ready.start("work", "--slots", "1")
    until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(1,)])
    worker.send_signal(signal.SIGTERM)
    assert worker.wait(timeout=20) == 0
    assert sorted(ready.target("select status from _rowvioli.status")) == [("new",), ("ok",)]
    assert ready.target("select count(*) from _rowvioli.runs") == [(1,)]


def test_with_the_limits_full_the_targets_connections_stay_at_the_running_tables_plus_one_per_worker(ready):
    tables = "\n".join(f'"public.slow{i}" = {{ key = ["id"] }}' for i in range(4))
    for i in range(4):
        slow(ready, f"slow{i}", 30, 1)
    apply(ready, source(ready, "erp", "parallel = 4", tables))
    ready.target("update _rowvioli.meta set max_running = 2")
    for _ in range(3):
        ready.start("work", "--slots", "4")
    until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(2,)])
    connections = """select count(*) from pg_stat_activity
                      where datname = current_database() and pid <> pg_backend_pid()"""
    # run processes started before the first claims committed find nothing and end; wait for them
    until(lambda: ready.target(connections) == [(2 + 3,)])
    seen, end = set(), time.monotonic() + 8  # four polling intervals
    while time.monotonic() < end:
        seen.add(ready.target(connections)[0][0])
        time.sleep(0.02)
    assert seen == {2 + 3}


def test_a_worker_survives_an_unreachable_target_and_loads_again_once_it_accepts_connections(ready):
    ready.source("create table customers (id int primary key)")
    ready.source("insert into customers values (1)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    worker = ready.start("work")
    until(lambda: ready.target("select status from _rowvioli.status") == [("ok",)])
    db = ready.target("select current_database()")[0][0]
    other = ready.target_url.rsplit("/", 1)[0] + "/postgres"
    _query(other, f"alter database {db} allow_connections false")
    _query(other, "select pg_terminate_backend(pid) from pg_stat_activity where datname = %s", [db])
    time.sleep(5)  # more than two of the worker's polling intervals
    assert worker.poll() is None
    _query(other, f"alter database {db} allow_connections true")
    ready.target("update _rowvioli.tables set requested_at = now()")
    until(lambda: ready.target("select count(*) from _rowvioli.runs where status = 'ok'") == [(2,)])


def said_after_sigterm(worker):
    """What a worker said on stderr, after it was asked to stop."""
    worker.send_signal(signal.SIGTERM)
    assert worker.wait(timeout=20) == 0
    return worker.stderr.read()


def test_work_says_its_start_and_what_it_loads_and_the_counts_equal_those_in_runs(ready):
    ready.source("create table customers (id int primary key)")
    ready.source("insert into customers values (1), (2)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    worker = ready.start("work", "--slots", "3")
    until(lambda: ready.target("select status from _rowvioli.status") == [("ok",)])
    db = ready.target("select current_database()")[0][0]
    err = said_after_sigterm(worker)
    assert f"started with 3 slots on {db}" in err
    assert "raw_erp.customers started, run 1" in err
    [(inserted, updated, deleted)] = ready.target("select inserted, updated, deleted from _rowvioli.runs")
    assert re.search(rf"raw_erp.customers ok after \d+\.\d+s: {inserted} inserted, {updated} updated, "
                     rf"{deleted} deleted", err)
    assert re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", err)


def test_work_says_a_failure_with_the_reason_of_the_status(ready):
    apply(ready, source(ready, "erp", "", '"public.missing" = { key = ["id"] }'))
    worker = ready.start("work")
    until(lambda: ready.target("select status from _rowvioli.status") == [("failed",)])
    [(reason,)] = ready.target("select reason from _rowvioli.status")
    assert re.search(rf"raw_erp.missing failed after \d+\.\d+s: {re.escape(reason)}", said_after_sigterm(worker))


def test_work_with_nothing_due_says_only_its_start(ready):
    worker = ready.start("work")
    time.sleep(3)
    err = said_after_sigterm(worker)
    assert " started with " in err
    assert "nothing due" not in err


def test_an_idle_work_on_sigterm_says_stopping_with_0_runs(ready):
    worker = ready.start("work")
    time.sleep(1)
    assert "stopping, 0 runs finish" in said_after_sigterm(worker)


def test_work_on_sigterm_says_stopping_and_the_run_still_says_ok(ready):
    slow(ready, "first", 3, 1)
    apply(ready, source(ready, "erp", "", '"public.first" = { key = ["id"] }'))
    worker = ready.start("work")
    until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(1,)])
    err = said_after_sigterm(worker)
    assert "stopping, 1 run finishes" in err
    assert "raw_erp.first ok after" in err


def test_a_run_ended_after_max_seconds_gives_a_failure_line(ready):
    slow(ready, "hanging", 30, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2", '"public.hanging" = { key = ["id"] }'))
    assert "raw_erp.hanging failed after 2.0s: ended after max_seconds = 2" in ready.run("run").stderr


def test_a_run_process_dying_before_its_claim_gives_a_line_with_its_exit_code(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    ready.target("alter table _rowvioli.runs add constraint broken check (false) not valid")
    assert re.search(r"run process ended with exit code 1 before it claimed", ready.run("run", timeout=20).stderr)
