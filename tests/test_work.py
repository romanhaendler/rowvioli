"""`rowvioli work`, the order of loading, both limits and `max_seconds` (spec tests 13, 14, 19)."""
import os
import subprocess
import time

import pytest
from conftest import ROWVIOLI
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
    env = {**os.environ, "ROWVIOLI_TARGET_URL": ready.target_url, "ROWVIOLI_KEY_FILE": str(ready.dir / "worker.key")}
    workers = [subprocess.Popen([ROWVIOLI, "work", "--slots", "4"], cwd=ready.dir, env=env) for _ in range(6)]
    highest, deadline = {"erp": 0, "crm": 0, "total": 0}, time.monotonic() + 60
    try:
        # probe pg_locks every 20 ms until every table was loaded once (experiment 5)
        while ready.target("select count(*) from _rowvioli.status where status <> 'ok'") != [(0,)]:
            assert time.monotonic() < deadline
            held = dict(ready.target(HELD))
            for name, n in [*held.items(), ("total", sum(held.values()))]:
                highest[name] = max(highest[name], n)
            time.sleep(0.02)
    finally:
        for w in workers:
            w.kill()
    # erp's parallel and max_running were reached, so the probe could have seen them broken
    assert highest["erp"] == 2 and highest["crm"] <= 3 and highest["total"] == 4


def test_run_ends_with_1_when_a_run_process_dies_before_claiming(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    ready.target("alter table _rowvioli.runs add constraint broken check (false) not valid")  # the claim fails
    r = ready.run("run", timeout=20)
    assert r.returncode == 1
    assert ready.target("select status from _rowvioli.status") == [("new",)]
