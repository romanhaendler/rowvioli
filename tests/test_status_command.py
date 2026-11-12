"""`rowvioli status`: the view as a table, read as the user reads it."""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def add(rv):
    """Creates sources 'erp' and 'crm'; returns a function that adds a table with the given facts."""
    assert rv.run("init").returncode == 0
    for s in ("erp", "crm"):
        rv.target("insert into _rowvioli.sources (name, type, target_schema) values (%s, 'postgres', %s)",
                  [s, "raw_" + s])

    def add(source, name, max_age="1h", **facts):
        cols = ", ".join(["source", "source_table", "target_table", "max_age", *facts])
        vals = ", ".join(["%s"] * (4 + len(facts)))
        rv.target(f"insert into _rowvioli.tables ({cols}) values ({vals})",
                  [source, name, name, max_age, *facts.values()])
    return add


def rows(rv, *args):
    r = rv.run("status", *args)
    assert r.returncode == 0, r.stderr
    header, *lines = r.stdout.splitlines()
    assert header.split() == ["source", "table", "max_age", "age", "due", "status", "reason"]
    return [line.split() for line in lines]


def test_one_row_per_table_with_max_age_due_and_status(rv, add):
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    add("erp", "late", loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0)
    add("erp", "fresh", max_age="1d", loaded_at=recent, attempted_at=recent, attempts=0)
    add("erp", "never")
    got = {r[1]: r for r in rows(rv)}
    assert got["late"][-2:] == ["now", "ok"]  # ok, yet due: nobody took it
    assert got["fresh"][3] == "1m" and got["fresh"][4] == "in" and got["fresh"][-1] == "ok"
    assert got["never"][2:] == ["1h", "now", "new"]  # no age


def test_a_failed_table_shows_its_reason_and_a_dead_run_worker_lost(rv, add):
    add("erp", "a", attempted_at="2026-01-01 00:00Z", attempts=1, reason="zero rows")
    add("erp", "b", attempted_at="2026-01-01 00:00Z", attempts=1)
    got = {r[1]: r for r in rows(rv)}
    assert got["a"][-3:] == ["failed", "zero", "rows"]
    assert got["b"][-3:] == ["failed", "worker", "lost"]


def test_durations_use_the_notation_of_the_definition(rv, add):
    add("erp", "t", max_age="2d")
    add("erp", "u", max_age="63m")
    got = {r[1]: r for r in rows(rv)}
    assert got["t"][2] == "2d"
    assert got["u"][2:4] == ["1h", "3m"]


def test_names_narrow_the_rows_and_a_disabled_table_is_not_shown(rv, add):
    add("erp", "a")
    add("erp", "b")
    add("crm", "c")
    add("crm", "off", enabled=False)
    assert [r[:2] for r in rows(rv)] == [["crm", "c"], ["erp", "a"], ["erp", "b"]]
    assert [r[:2] for r in rows(rv, "erp")] == [["erp", "a"], ["erp", "b"]]
    assert [r[:2] for r in rows(rv, "erp", "b")] == [["erp", "b"]]


def test_status_needs_the_target_only_and_names_init_without_the_schema(rv, add):
    assert rv.run("status").returncode == 0  # the harness sets a key file; the command ignores it
    rv.target("drop schema _rowvioli cascade")
    r = rv.run("status")
    assert r.returncode != 0 and "rowvioli init" in r.stderr
