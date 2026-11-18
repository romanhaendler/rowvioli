"""Killed runs and readers (spec tests 9, 10, 22). Runs are held at a step from the SQL side, then killed with -9."""
import json
import os
import subprocess
import threading
from datetime import timedelta

import psycopg
import pytest

from conftest import until
from test_run import apply, definition, ok, rows


SOURCE = """
create table customers (customer_no int primary key, name text);
insert into customers select i, 'c' || i from generate_series(1, 5) i;
create table delay (seconds float, after int);
insert into delay values (0, 0);
create function slowly(i int) returns int volatile language sql as 'select pg_sleep((select seconds from delay where i > after)); select i';
create view slow as select slowly(customer_no) as customer_no, name from customers
"""
SLOW = '"public.slow" = { key = ["customer_no"] }\n'


@pytest.fixture
def slow(rv):
    """A loaded mirror raw_erp.slow of a source view that sleeps per row once `delay` is set, and changes in the
    source, so that a run that publishes would change the mirror."""
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    for statement in SOURCE.strip().split(";\n"):
        rv.source(statement)
    apply(rv, definition(rv, SLOW))
    ok(rv)
    rv.source("update customers set name = 'changed' where customer_no = 1")
    rv.source("delete from customers where customer_no = 2")
    rv.source("insert into customers values (6, 'new')")
    rv.target("update _rowvioli.tables set requested_at = now()")
    return rv


def status(rv):
    return rv.target("select status, reason from _rowvioli.status")[0]


def held_table_locks(rv):
    return rv.target("""select count(*) from pg_locks where locktype = 'advisory' and objsubid = 2 and classid <> 0
                          and database = (select oid from pg_database where datname = current_database())""")[0][0]


def waiting_on(rv, table, mode="AccessShareLock"):
    """The pid of a backend (the run's) that waits for a `mode` lock on `table`, or None."""
    pids = rv.target("""select pid from pg_locks where not granted and mode = %s and relation = to_regclass(%s)
                          and database = (select oid from pg_database where datname = current_database())""",
                     [mode, table])
    return pids[0][0] if pids else None


def kill_and_check(rv, worker):
    """Kills the run while it is held; then: lock released, failed with `worker lost`, in its pause."""
    assert status(rv) == ("loading", None) and held_table_locks(rv) == 1
    assert len(rv.kill_runs(worker)) == 1
    until(lambda: status(rv) != ("loading", None))
    assert held_table_locks(rv) == 0
    assert status(rv) == ("failed", "worker lost")
    assert rv.target("select due_at - attempted_at, attempts from _rowvioli.status") == [(timedelta(minutes=1), 1)]
    assert rv.target("select status, finished_at from _rowvioli.runs order by run desc limit 1") == [("running", None)]
    out, _ = worker.communicate(timeout=10)  # `run` ends: nothing is due or loading any more
    assert worker.returncode == 1
    assert json.loads(out)["tables"] == {"raw_erp.slow": {"status": "failed", "reason": "worker lost"}}


def test_the_next_run_closes_the_row_of_a_dead_run(slow):
    with psycopg.connect(slow.target_url) as holder:
        holder.execute("lock table raw_erp.slow in access exclusive mode")
        worker = slow.start("run")
        until(lambda: waiting_on(slow, "raw_erp.slow"))
        kill_and_check(slow, worker)
        holder.rollback()
    slow.target("update _rowvioli.tables set requested_at = now()")
    ok(slow)
    assert slow.target("""select status, reason, finished_at is not null from _rowvioli.runs
                           order by run desc offset 1 limit 1""") == [("failed", "worker lost", True)]
    assert slow.target("select count(*) from _rowvioli.runs where status = 'running'") == [(0,)]


def mirror(rv):
    return rows(rv.target, "select * from raw_erp.slow"), rows(rv.target, "select * from raw_erp.slow__log")


def hold_filling(rv):
    """Starts `run` and returns it once it is held while filling a staging table that already has rows."""
    # ~25 MB before the sleep, so that the driver hands over its first batches (they are ~16 MB each)
    rv.source("insert into customers select i, repeat('x', 10000) from generate_series(1000, 3500) i")
    rv.source("update delay set seconds = 1, after = 3400")
    worker = rv.start("run")
    until(lambda: rv.target("""select count(*) from pg_class where relpersistence = 't' and relkind = 'r'
                                 and pg_relation_size(oid) > 0""")[0][0], timeout=30)
    return worker


def test_a_run_killed_while_filling_leaves_the_mirror_and_releases_its_lock(slow):
    before = mirror(slow)
    kill_and_check(slow, hold_filling(slow))
    assert mirror(slow) == before


def test_while_filling_the_status_shows_the_rows_written_so_far_and_those_of_the_last_run(slow):
    assert slow.target("select rows_written, rows_last_run from _rowvioli.status") == [(None, None)]
    hold_filling(slow)
    written, last = slow.target("select rows_written, rows_last_run from _rowvioli.status")[0]
    assert written > 0 and last == 5


@pytest.mark.parametrize("mode, waits_for", [
    ("access exclusive", "AccessShareLock"),  # blocks reads: held at the diff
    ("exclusive", "RowExclusiveLock"),  # blocks only writes: held at publishing, change log rows already inserted
])
def test_a_run_killed_at_the_diff_or_while_publishing_leaves_the_mirror_and_releases_its_lock(slow, mode, waits_for):
    before = mirror(slow)
    with psycopg.connect(slow.target_url) as holder:
        holder.execute(f"lock table raw_erp.slow in {mode} mode")
        worker = slow.start("run")
        until(lambda: waiting_on(slow, "raw_erp.slow", waits_for))
        kill_and_check(slow, worker)  # while the mirror is still locked
        holder.rollback()
    assert mirror(slow) == before


def test_a_worker_killed_hard_takes_its_runs_with_it(slow):
    """Decision 33: after kill -9 of `work`, its run process ends too, so the run counts as `worker lost`."""
    before = mirror(slow)
    with psycopg.connect(slow.target_url) as holder:
        holder.execute("lock table raw_erp.slow in access exclusive mode")
        worker = slow.start("work")
        until(lambda: waiting_on(slow, "raw_erp.slow"))
        [run] = [int(x) for x in subprocess.run(["pgrep", "-P", str(worker.pid)], capture_output=True,
                                                 text=True).stdout.split()]
        worker.kill()
        worker.wait()
        until(lambda: not alive(run))
        until(lambda: status(slow) != ("loading", None))
        holder.rollback()
    assert status(slow) == ("failed", "worker lost")
    assert held_table_locks(slow) == 0
    assert mirror(slow) == before


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_a_run_whose_server_process_is_killed_fails_and_run_says_so(slow):
    """docs/target.md "Failures": the target drops the connection, the run ends without publishing."""
    before = mirror(slow)
    with psycopg.connect(slow.target_url) as holder:
        holder.execute("lock table raw_erp.slow in access exclusive mode")
        worker = slow.start("run")
        slow.target("select pg_terminate_backend(%s)", [until(lambda: waiting_on(slow, "raw_erp.slow"))])
        out, err = worker.communicate(timeout=20)
        holder.rollback()
    assert worker.returncode == 1
    assert json.loads(out)["tables"] == {"raw_erp.slow": {"status": "failed", "reason": "connection to the target lost"}}
    assert "Traceback" not in err
    assert held_table_locks(slow) == 0
    # the run cannot write its reason without a connection, its worker writes it (ticket 15)
    assert status(slow) == ("failed", "connection to the target lost")
    assert slow.target("select status, reason from _rowvioli.runs order by run desc limit 1") == [
        ("failed", "connection to the target lost")]
    assert mirror(slow) == before


def test_run_whose_own_connection_the_target_drops_says_so_in_one_line(slow):
    """Ticket 11: the target's message without the query that was sent."""
    with psycopg.connect(slow.target_url) as holder:
        holder.execute("lock table raw_erp.slow in access exclusive mode")
        worker = slow.start("run")
        run = until(lambda: waiting_on(slow, "raw_erp.slow"))
        slow.target("""select pg_terminate_backend(pid) from pg_stat_activity
                        where datname = current_database() and pid not in (pg_backend_pid(), %s, %s)""",
                    [run, holder.info.backend_pid])
        out, err = worker.communicate(timeout=20)
        holder.rollback()
    assert worker.returncode == 1 and out == ""
    assert "SELECT" not in err and "terminating connection" in err.splitlines()[-1], err


def test_a_reader_never_sees_an_empty_or_half_loaded_mirror(slow):
    """With and without a key: every count a reader sees is the old or the new state, never anything between."""
    apply(slow, definition(slow, '"public.customers" = { key = ["customer_no"] }\n"public.notes" = {}\n'))
    slow.source("create table notes (n int, x text)")
    states = {  # each deletes, updates and inserts relative to the other, deleting less than max_delete_share
        "A": ("select i, 'a' || i from generate_series(1, 1000) i", 1000),
        "B": ("select i, 'b' || i from generate_series(301, 1600) i", 1300),
    }

    def load(state):
        query, _ = states[state]
        for table in ("customers", "notes"):
            slow.source(f"truncate {table}")
            slow.source(f"insert into {table} {query}")
        ok(slow, "erp")

    load("A")
    seen, stop = set(), threading.Event()

    def read():
        with psycopg.connect(slow.target_url, autocommit=True) as c:
            while not stop.is_set():
                seen.add(c.execute("select (select count(*) from raw_erp.customers),"
                                   " (select count(*) from raw_erp.notes)").fetchone())

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for state in "BABABA":
            load(state)
    finally:
        stop.set()
        reader.join()
    counts = {n for _, n in states.values()}
    assert {c for c, _ in seen} == counts and {n for _, n in seen} == counts


def test_a_run_killed_after_its_claim_gives_a_worker_lost_line(slow):
    with psycopg.connect(slow.target_url) as holder:
        holder.execute("lock table raw_erp.slow in access exclusive mode")
        worker = slow.start("run")
        until(lambda: waiting_on(slow, "raw_erp.slow"))
        slow.kill_runs(worker)
        _, err = worker.communicate(timeout=20)
        holder.rollback()
    assert "raw_erp.slow started" in err
    assert "raw_erp.slow failed after" in err and err.rstrip().endswith("worker lost")
