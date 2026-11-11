"""Killed runs and readers (spec tests 9, 10, 22). Runs are held at a step from the SQL side, then killed with -9."""
import json
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


def waiting_on(rv, statement):
    """The run's target backend waits for a lock while running `statement`."""
    return rv.target("""select count(*) from pg_stat_activity where datname = current_database()
                          and wait_event_type = 'Lock' and query like %s""", [statement + "%"])[0][0]


def kill_and_check(rv, worker):
    """Kills the run while it is held; then: lock released, failed with `worker lost`, in its pause."""
    assert status(rv) == ("loading", None) and held_table_locks(rv) == 1
    assert len(rv.kill_runs(worker)) == 1
    until(lambda: status(rv) != ("loading", None))
    assert held_table_locks(rv) == 0
    assert status(rv) == ("failed", "worker lost")
    assert rv.target("select due_at - attempted_at, attempts from _rowvioli.status") == [(timedelta(minutes=1), 1)]
    assert rv.target("select status, finished_at from _rowvioli.runs order by run desc limit 1") == [("running", None)]
    worker.wait(timeout=10)  # `run` ends: nothing is due or loading any more


def mirror(rv):
    return rows(rv.target, "select * from raw_erp.slow"), rows(rv.target, "select * from raw_erp.slow__log")


def test_a_run_killed_while_filling_leaves_the_mirror_and_releases_its_lock(slow):
    before = mirror(slow)
    # ~25 MB before the sleep, so that the driver hands over its first batches (they are ~16 MB each)
    slow.source("insert into customers select i, repeat('x', 10000) from generate_series(1000, 3500) i")
    slow.source("update delay set seconds = 1, after = 3400")
    worker = slow.start("run")
    # held inside COPY into a staging table that already has rows
    until(lambda: slow.target("""select count(*) from pg_stat_activity a, pg_class c
                                   where a.datname = current_database() and a.query like 'COPY %_stage%'
                                     and c.relname = '_stage' and pg_relation_size(c.oid) > 0""")[0][0], timeout=30)
    kill_and_check(slow, worker)
    assert mirror(slow) == before


@pytest.mark.parametrize("mode, statement", [
    ("access exclusive", "CREATE TEMP TABLE _diff"),  # blocks reads: held at the diff
    ("exclusive", "DELETE FROM"),  # blocks only writes: held at publishing, change log rows already inserted
])
def test_a_run_killed_at_the_diff_or_while_publishing_leaves_the_mirror_and_releases_its_lock(slow, mode, statement):
    before = mirror(slow)
    with psycopg.connect(slow.target_url) as holder:
        holder.execute(f"lock table raw_erp.slow in {mode} mode")
        worker = slow.start("run")
        until(lambda: waiting_on(slow, statement))
        kill_and_check(slow, worker)  # while the mirror is still locked
        holder.rollback()
    assert mirror(slow) == before


def test_a_run_whose_server_process_is_killed_fails_and_run_says_so(slow):
    """README "Failures": the target drops the connection, the run ends without publishing."""
    before = mirror(slow)
    with psycopg.connect(slow.target_url) as holder:
        holder.execute("lock table raw_erp.slow in access exclusive mode")
        worker = slow.start("run")
        until(lambda: waiting_on(slow, "CREATE TEMP TABLE _diff"))
        slow.target("""select pg_terminate_backend(pid) from pg_stat_activity
                        where datname = current_database() and query like 'CREATE TEMP TABLE _diff%'""")
        out, err = worker.communicate(timeout=20)
        holder.rollback()
    assert worker.returncode == 1
    assert json.loads(out)["tables"] == {"raw_erp.slow": {"status": "failed", "reason": "connection to the target lost"}}
    assert "Traceback" not in err
    assert held_table_locks(slow) == 0
    assert status(slow) == ("failed", "worker lost")  # the reason cannot be written without a connection
    assert mirror(slow) == before


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
