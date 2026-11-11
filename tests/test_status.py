"""The view _rowvioli.status, fed with rows written by SQL (no run needed)."""
from datetime import timedelta

import psycopg
import pytest


@pytest.fixture
def table(rv):
    """Creates source 'erp' and returns a function that adds a table with the given facts."""
    assert rv.run("init").returncode == 0
    rv.target("insert into _rowvioli.sources (name, type, target_schema) values ('erp', 'postgres', 'raw_erp')")

    def add(name="t", max_age="1h", **facts):
        cols = ", ".join(["source", "source_table", "target_table", "max_age", *facts])
        vals = ", ".join(["'erp'", "%s", "%s", "%s", *(["%s"] * len(facts))])
        return rv.target(f"insert into _rowvioli.tables ({cols}) values ({vals}) returning id",
                         [name, name, max_age, *facts.values()])[0][0]
    return add


def row(rv, id, cols="status, reason"):
    return rv.target(f"select {cols} from _rowvioli.status where id = %s", [id])[0]


def pause(rv, id):
    return row(rv, id, "due_at - attempted_at")[0]


def test_never_attempted_is_new_and_due_now(rv, table):
    id = table()
    assert row(rv, id, "status, reason, due_at = now()") == ("new", None, True)


def test_succeeded_is_ok_and_due_one_max_age_after_loading(rv, table):
    id = table(max_age="10m", loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0)
    assert row(rv, id) == ("ok", None)
    assert row(rv, id, "due_at - loaded_at")[0] == timedelta(minutes=10)


def test_failed_shows_its_reason_or_worker_lost(rv, table):
    with_reason = table("a", attempted_at="2026-01-01 00:00Z", attempts=1, reason="zero rows")
    without = table("b", attempted_at="2026-01-01 00:00Z", attempts=1)
    assert row(rv, with_reason) == ("failed", "zero rows")
    assert row(rv, without) == ("failed", "worker lost")


def test_loading_while_the_table_lock_is_held(rv, table):
    id = table(attempted_at="2026-01-01 00:00Z", attempts=1)
    source_id = row(rv, id, "source_id")[0]
    with psycopg.connect(rv.target_url, autocommit=True) as holder:
        holder.execute("select pg_advisory_lock(%s, %s)", [source_id, id])
        assert row(rv, id) == ("loading", None)
    assert row(rv, id) == ("failed", "worker lost")


def test_pause_starts_at_one_minute_and_doubles(rv, table):
    one = table("a", attempted_at="2026-01-01 00:00Z", attempts=1)
    three = table("b", attempted_at="2026-01-01 00:00Z", attempts=3)
    assert pause(rv, one) == timedelta(minutes=1)
    assert pause(rv, three) == timedelta(minutes=4)


def test_pause_never_exceeds_max_age(rv, table):
    many = table("a", max_age="1h", attempted_at="2026-01-01 00:00Z", attempts=10)
    short = table("b", max_age="30s", attempted_at="2026-01-01 00:00Z", attempts=1)
    huge = table("c", max_age="1d", attempted_at="2026-01-01 00:00Z", attempts=1000)
    assert pause(rv, many) == timedelta(hours=1)
    assert pause(rv, short) == timedelta(seconds=30)
    assert pause(rv, huge) == timedelta(days=1)


def test_failed_table_is_not_due_until_its_pause_is_over(rv, table):
    id = table(attempts=1)
    rv.target("update _rowvioli.tables set attempted_at = now() where id = %s", [id])
    assert row(rv, id, "due_at > now()")[0]
    rv.target("update _rowvioli.tables set attempted_at = now() - interval '2 minutes' where id = %s", [id])
    assert row(rv, id, "due_at <= now()")[0]


def test_a_request_after_the_last_attempt_makes_it_due_at_the_request(rv, table):
    id = table(loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0,
               requested_at="2026-01-01 00:05Z")
    assert row(rv, id, "due_at = requested_at")[0]
    rv.target("update _rowvioli.tables set attempted_at = '2026-01-01 00:06Z' where id = %s", [id])
    assert row(rv, id, "due_at - loaded_at")[0] == timedelta(hours=1)


def test_a_shortened_max_age_changes_due_at_without_a_run(rv, table):
    id = table(max_age="1h", loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0)
    rv.target("update _rowvioli.tables set max_age = '5m' where id = %s", [id])
    assert row(rv, id, "due_at - loaded_at")[0] == timedelta(minutes=5)


def test_disabled_tables_are_not_in_the_status(rv, table):
    id = table(enabled=False)
    assert rv.target("select count(*) from _rowvioli.status where id = %s", [id]) == [(0,)]
