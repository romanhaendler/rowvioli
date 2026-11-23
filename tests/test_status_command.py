"""`rowvioli status`: the view as a table, read as the user reads it."""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest


@pytest.fixture
def add(rv):
    """Creates sources 'erp' and 'crm'; returns a function that adds a table with the given facts."""
    assert rv.run("init").returncode == 0
    for s in ("erp", "crm"):
        rv.target("insert into _rowvioli.sources (name, type) values (%s, 'postgres')", [s])

    def add(source, name, max_age="1h", **facts):
        cols = ", ".join(["source", "source_table", "target_schema", "target_table", "max_age", *facts])
        vals = ", ".join(["%s"] * (5 + len(facts)))
        rv.target(f"insert into _rowvioli.tables ({cols}) values ({vals})",
                  [source, name, "raw_" + source, name, max_age, *facts.values()])
    return add


def rows(rv, *args):
    r = rv.run("status", *args)
    assert r.returncode == 0, r.stderr
    header, *lines = r.stdout.splitlines()
    assert header.split() == ["source", "table", "target", "max_age", "age", "due", "status", "reason"]
    return [line.split() for line in lines]


def test_one_row_per_table_with_max_age_due_and_status(rv, add):
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    add("erp", "late", loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0)
    add("erp", "fresh", max_age="1d", loaded_at=recent, attempted_at=recent, attempts=0)
    add("erp", "never")
    got = {r[1]: r for r in rows(rv)}
    assert got["late"][-2:] == ["now", "ok"]  # ok, yet due: nobody took it
    assert "in" in got["fresh"] and got["fresh"][-1] == "ok"  # how the age splits depends on rounding
    assert got["never"][2:] == ["raw_erp.never", "1h", "now", "new"]  # the target name; no age


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
    assert got["t"][2:4] == ["raw_erp.t", "2d"]
    assert got["u"][3:5] == ["1h", "3m"]


def test_names_narrow_the_rows_and_a_disabled_table_is_not_shown(rv, add):
    add("erp", "a")
    add("erp", "b")
    add("crm", "c")
    add("crm", "off", enabled=False)
    assert [r[:2] for r in rows(rv)] == [["crm", "c"], ["erp", "a"], ["erp", "b"]]
    assert [r[:2] for r in rows(rv, "erp")] == [["erp", "a"], ["erp", "b"]]
    assert [r[:2] for r in rows(rv, "erp", "b")] == [["erp", "b"]]


def test_status_needs_the_target_only_and_names_init_without_the_schema(rv, add):
    assert rv.run("status", env={"ROWVIOLI_KEY_FILE": ""}).returncode == 0  # no key file: the command needs none
    rv.target("drop schema _rowvioli cascade")
    r = rv.run("status")
    assert r.returncode != 0 and "rowvioli init" in r.stderr


def test_a_loading_table_without_progress_shows_no_reason(rv, add):
    add("erp", "t", attempted_at="2026-01-01 00:00Z", attempts=1, reason="old failure")
    [(source_id, id)] = rv.target("select source_id, id from _rowvioli.status")
    with psycopg.connect(rv.target_url, autocommit=True) as holder:
        holder.execute("select pg_advisory_lock(%s, %s)", [source_id, id])
        assert rows(rv)[0][-1] == "loading"
        assert rv.target("select reason from _rowvioli.status") == [("old failure",)]


def test_progress_shows_to_a_role_with_pg_read_all_stats_and_is_empty_without(rv, add):
    add("erp", "t")
    [(source_id, id)] = rv.target("select source_id, id from _rowvioli.status")
    # roles belong to the cluster, which other tests share: names of their own
    for role, extra in (("plain_reader", ""), ("stats_reader", " in role pg_read_all_stats")):
        rv.target(f"create role {role} login password 'v'{extra}")
        rv.target(f"grant usage on schema _rowvioli to {role}")
        rv.target(f"grant select on _rowvioli.status to {role}")

    def written(role):
        url = rv.target_url.replace("postgres:x@", f"{role}:v@")
        with psycopg.connect(url) as c:
            return c.execute("select status, rows_written from _rowvioli.status").fetchone()
    # a run's session as the worker's role: the table lock, then a COPY into staging that is still going on
    with psycopg.connect(rv.target_url, autocommit=True) as run:
        run.execute("select pg_advisory_lock(%s, %s)", [source_id, id])
        run.execute("create temp table _stage (i int)")
        with run.cursor().copy("copy _stage from stdin") as copy:
            for i in range(200_000):  # enough that psycopg has sent most of it
                copy.write_row([i])
            assert written("plain_reader") == ("loading", None)
            assert written("stats_reader")[0] == "loading" and written("stats_reader")[1] > 0


def test_a_role_that_may_only_read_the_status_view_can_run_status(rv, add):
    add("erp", "t")
    rv.target("create role viewer login password 'v'")
    rv.target("grant usage on schema _rowvioli to viewer")
    rv.target("grant select on _rowvioli.status to viewer")
    url = rv.target_url.replace("postgres:x@", "viewer:v@")
    r = rv.run("status", env={"ROWVIOLI_TARGET_URL": url})
    assert r.returncode == 0 and "erp" in r.stdout, r.stderr
    rv.target("drop schema _rowvioli cascade")
    r = rv.run("status", env={"ROWVIOLI_TARGET_URL": url})
    assert r.returncode != 0 and "rowvioli init" in r.stderr and "Traceback" not in r.stderr


def test_a_reason_with_control_characters_is_printed_with_question_marks(rv, add):
    add("erp", "a", attempted_at="2026-01-01 00:00Z", attempts=1, reason="bad \033[2J value\r1")
    out = rv.run("status").stdout
    assert "bad ?[2J value?1" in out and "\033" not in out and "\r" not in out


def test_names_with_control_characters_are_printed_with_question_marks(rv, add):
    rv.target("insert into _rowvioli.sources (name, type) values (%s, 'postgres')", ["e\033rp"])
    add("e\033rp", "a\033[2J\rb")  # applied by an older version, which let such names in
    out = rv.run("status").stdout
    assert "e?rp" in out and "a?[2J?b" in out and "raw_e?rp.a?[2J?b" in out, out
    assert "\033" not in out and "\r" not in out, repr(out)
