import json
import re

import psycopg
import pytest

from conftest import until
from test_checks import failed
from test_columns_go_and_come import log_replays
from test_history import LOADED_AT, LOG_FALSE, MIRROR, again, at
from test_keys import primary_key
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)

SHAPE = """
select table_name, column_name, data_type from information_schema.columns
 where table_schema = '_rowvioli' order by 1, 2
"""


def test_init_twice_leaves_the_same_schema_and_meta(rv):
    first = rv.run("init")
    assert first.returncode == 0, first.stderr
    shape = rv.target(SHAPE)
    assert {r[0] for r in shape} == {"sources", "tables", "runs", "meta", "status", "columns", "columns__log",
                                  "columns__history"}

    second = rv.run("init")
    assert second.returncode == 0, second.stderr
    assert rv.target(SHAPE) == shape
    assert rv.target("select schema_version, max_running from _rowvioli.meta") == [(4, 20)]


def test_the_columns_table_and_its_log_are_read_by_the_tables_id_through_an_index(rv):  # every run reads them so
    rv.run("init")
    assert rv.target("select tablename from pg_indexes where schemaname = '_rowvioli' and tablename like 'columns%%' "
                     "and indexdef like '%%(id)' order by 1") == [("columns",), ("columns__log",)]


def test_init_keeps_what_is_there(rv):
    rv.run("init")
    rv.target("update _rowvioli.meta set max_running = 7")
    rv.target("insert into _rowvioli.sources (name, type) values ('erp', 'postgres')")
    assert rv.run("init").returncode == 0
    assert rv.target("select max_running from _rowvioli.meta") == [(7,)]
    assert rv.target("select name from _rowvioli.sources") == [("erp",)]


def version_3(rv):
    """A target as version 3 left it: without the version columns of runs and the columns table."""
    rv.target("drop view _rowvioli.columns__history")
    rv.target("drop table _rowvioli.columns__log, _rowvioli.columns")
    rv.target("alter table _rowvioli.runs drop column program_version, drop column driver_version")
    rv.target("update _rowvioli.meta set schema_version = 3")


def test_init_brings_a_version_3_target_to_4_and_changes_nothing_else(rv):
    rv.run("init")
    shape = rv.target(SHAPE)
    rv.target("insert into _rowvioli.sources (name, type) values ('erp', 'postgres')")
    version_3(rv)
    assert rv.target(SHAPE) != shape
    assert rv.run("init").returncode == 0
    assert rv.target(SHAPE) == shape
    assert rv.target("select schema_version from _rowvioli.meta") == [(4,)]
    assert rv.target("select name from _rowvioli.sources") == [("erp",)]


READY = "the schema _rowvioli is ready in the target\n"


def test_init_from_version_3_prints_the_grants_a_worker_needs_and_they_are_enough_to_load(erp):
    assert erp.run("init").stdout == READY  # a target of version 4 is told nothing new
    version_3(erp)
    r = erp.run("init")
    assert r.returncode == 0, r.stderr
    grants = [line for line in r.stdout.splitlines() if line.startswith("GRANT")]
    assert grants and all(line.endswith(" TO worker;") for line in grants), r.stdout
    assert erp.run("init").stdout == READY
    # a worker's role with the grants of docs/operation.md and those printed (roles belong to the cluster: its own name)
    role, db = f"worker_{erp.target_url.rsplit('/', 1)[1]}", erp.target_url.rsplit("/", 1)[1]
    for statement in [f"CREATE ROLE {role} LOGIN PASSWORD 'w'", f"GRANT USAGE ON SCHEMA _rowvioli TO {role}",
                      f"GRANT SELECT ON _rowvioli.sources, _rowvioli.tables, _rowvioli.meta, _rowvioli.status TO {role}",
                      f"GRANT UPDATE ON _rowvioli.tables TO {role}",
                      f"GRANT SELECT, INSERT, UPDATE ON _rowvioli.runs TO {role}",
                      f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA _rowvioli TO {role}",
                      f"GRANT CREATE ON DATABASE {db} TO {role}",
                      *(g.replace(" TO worker;", f" TO {role}") for g in grants)]:
        erp.target(statement)
    url = {"ROWVIOLI_TARGET_URL": erp.target_url.replace("postgres:x@", f"{role}:w@")}
    for change in (None, "alter table customers drop column city"):  # a first fill, then a column that goes
        if change:
            erp.source(change)
            erp.target("update _rowvioli.tables set requested_at = now()")
        r = erp.run("run", env=url)
        assert r.returncode == 0, r.stdout + r.stderr
    assert erp.target("select mirror from _rowvioli.columns where \"column\" = 'city'") == [(False,)]


@pytest.mark.parametrize("given, lacking", [(0, "columns"), (1, "columns__log")])
def test_a_worker_without_the_grants_init_printed_is_told_where_they_are(erp, given, lacking):
    version_3(erp)
    grants = [line for line in erp.run("init").stdout.splitlines() if line.startswith("GRANT")]
    role, db = f"worker_{erp.target_url.rsplit('/', 1)[1]}", erp.target_url.rsplit("/", 1)[1]
    try:
        for statement in [f"CREATE ROLE {role} LOGIN PASSWORD 'w'", f"GRANT USAGE ON SCHEMA _rowvioli TO {role}",
                          f"GRANT SELECT ON _rowvioli.sources, _rowvioli.tables, _rowvioli.meta, _rowvioli.status "
                          f"TO {role}", f"GRANT UPDATE ON _rowvioli.tables TO {role}",
                          f"GRANT SELECT, INSERT, UPDATE ON _rowvioli.runs TO {role}",
                          f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA _rowvioli TO {role}",
                          f"GRANT CREATE ON DATABASE {db} TO {role}",
                          *(g.replace(" TO worker;", f" TO {role}") for g in grants[:given])]:
            erp.target(statement)
        url = {"ROWVIOLI_TARGET_URL": erp.target_url.replace("postgres:x@", f"{role}:w@")}
        reason = json.loads(erp.run("run", env=url).stdout)["tables"]["raw_erp.customers"]["reason"]
        assert reason.endswith(f"permission denied for table {lacking}: the worker's role lacks a right on "
                          f"_rowvioli.{lacking}, which rowvioli init printed with the upgrade to version 4 "
                          '(docs/operation.md "The target")'), reason
    finally:
        erp.target(f"drop owned by {role}")
        erp.target(f"drop role {role}")


@pytest.mark.parametrize("change", ["drop column city", "alter column city type integer using length(city)"])
def test_the_first_run_after_the_upgrade_records_what_it_changed_by_its_cause_and_notifies(erp, change):  # story 45
    assert erp.run("run").returncode == 0
    # as the released version leaves a target: no columns table, no comment on _op
    erp.target("comment on column raw_erp.customers__log._op is null")
    version_3(erp)
    assert erp.run("init").returncode == 0
    listener = psycopg.connect(erp.target_url, autocommit=True)
    listener.execute("listen rowvioli_schema")
    erp.source(f"alter table customers {change}")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert erp.run("run").returncode == 0
    [(run,)] = erp.target("select max(run) from _rowvioli.runs")
    # the program before recorded no versions, so what the run changed is the reader's (decision 54)
    recorded = {c: (mirror, by) for c, mirror, by in erp.target(
        'select "column", mirror, "by" from _rowvioli.columns__log where _run = %s', [run])}
    assert recorded == {"customer_no": (True, "found"), "name": (True, "found"),
                        **({"city": (False, "reader")} if change.startswith("drop") else
                           {"city": (True, "reader"), f"city__{run}": (False, "reader")})}
    assert [json.loads(n.payload) for n in listener.notifies(timeout=1, stop_after=1)] == [
        {"schema": "raw_erp", "table": "customers", "run": run}]
    listener.close()


def released(rv):
    """The upgrade of a target as the released version leaves it: no columns table, no comment on _op."""
    rv.target("comment on column raw_erp.customers__log._op is null")
    version_3(rv)
    assert rv.run("init").returncode == 0


HAND = "alter table raw_erp.customers drop constraint customers_pkey, add primary key (customer_no, name)"
def elsewhere(rv):
    """The definition with the same key, changed elsewhere: it differs from that of the last successful run."""
    return definition(rv).replace('max_age = "1h"', 'max_age = "2h"')


KEY_LOG ='select _op, "column", "key", "by" from _rowvioli.columns__log where _run = (select max(run) from _rowvioli.runs)'


@pytest.mark.parametrize("cause", ["hand", "definition"])
def test_a_key_changed_before_the_upgrade_is_told_by_the_change_log_and_keeps_the_history(erp, cause):  # story 45
    ok(erp)
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    erp.source("update customers set name = 'Anna2' where customer_no = 1")  # a U the other key never saw
    moments.append((again(erp), rows(erp.target, MIRROR)))
    if cause == "hand":
        erp.target(HAND)
        apply(erp, elsewhere(erp))
    else:
        apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    released(erp)
    erp.source("update customers set city = 'Köln' where customer_no = 2")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    assert primary_key(erp) == (["customer_no"] if cause == "hand" else ["customer_no", "name"])
    changed = erp.target("select _op, customer_no from raw_erp.customers__log where _run = "
                         "(select max(run) from _rowvioli.runs) order by 1, 2")
    assert changed == ([("U", 2)] if cause == "hand" else [("D", 1), ("D", 2), ("D", 3), ("I", 1), ("I", 2), ("I", 3)])
    for moment, mirror in moments:
        assert at(erp, moment) == mirror, moment
    log_replays(erp)
    assert erp.target(KEY_LOG + ' and "column" in (\'customer_no\', \'name\') order by 2') == [
        ("I", "customer_no", 1, cause), ("I", "name", None if cause == "hand" else 2, cause)]


def test_a_key_changed_by_hand_before_the_upgrade_is_told_by_the_definition_of_the_last_successful_run(erp):
    ok(erp)  # a change log of first rows only, which either key could have written
    erp.target(HAND)
    released(erp)
    again(erp)
    assert primary_key(erp) == ["customer_no"]
    assert erp.target(KEY_LOG + " and \"column\" = 'customer_no'") == [("I", "customer_no", 1, "hand")]
    log_replays(erp)


def test_a_key_changed_before_the_upgrade_that_nothing_in_the_target_tells_stops_with_the_statement_that_does(erp):
    ok(erp)
    erp.target(HAND)
    apply(erp, elsewhere(erp))
    released(erp)
    before = rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp).replace("***", "x")  # the source's password is x, and the reason hides it
    statement = """COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '[{"key": ["customer_no"]}]'"""
    assert reason == (
        "the primary key of raw_erp.customers is (customer_no, name), the definition's key is (customer_no), and "
        "nothing in the target tells which of them the change log raw_erp.customers__log was written under: say it, "
        f"{statement} where a person changed the primary key, which the next run puts back, or "
        """COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '[{"key": ["customer_no", "name"]}]' where the """
        "definition changed the key")
    assert (rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")) == before
    erp.target(statement)
    again(erp)
    assert primary_key(erp) == ["customer_no"]
    assert erp.target(KEY_LOG + " and \"column\" = 'customer_no'") == [("I", "customer_no", 1, "hand")]
    log_replays(erp)


def test_a_change_log_a_run_would_not_write_to_stops_first_also_where_nothing_tells_who_changed_the_key(erp):
    ok(erp)
    erp.target(HAND)
    apply(erp, definition(erp, LOG_FALSE))  # the definition changed, and the change log is ended
    released(erp)
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp).replace("***", "x")  # the source's password is x, and the reason hides it
    assert reason == ('the change log raw_erp.customers__log exists and this run would not write to it (log = false or '
                      'no key): drop it with its history view (DROP TABLE "raw_erp"."customers__log" CASCADE), or '
                      "rename both with the mirror")
    erp.target('DROP TABLE "raw_erp"."customers__log" CASCADE')  # the way out, after which the definition's key holds
    again(erp)
    assert primary_key(erp) == ["customer_no"]
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")


def test_init_on_an_empty_target_prints_only_that_it_is_ready(rv):
    r = rv.run("init")
    assert r.returncode == 0 and r.stdout == READY, r.stderr


def test_init_refuses_a_target_older_than_version_3_and_leaves_it(rv):  # the steps begin at 3
    rv.run("init")
    version_3(rv)
    rv.target("update _rowvioli.meta set schema_version = 2")
    shape = rv.target(SHAPE)
    r = rv.run("init")
    assert r.returncode != 0
    assert re.search(r"\b2\b", r.stderr) and re.search(r"\b4\b", r.stderr), r.stderr
    assert rv.target(SHAPE) == shape
    assert rv.target("select schema_version from _rowvioli.meta") == [(2,)]


@pytest.mark.parametrize("command", [["init"], ["apply", "sources"], ["run"], ["work"]])
def test_every_command_using_the_target_refuses_another_schema_version_naming_both(rv, command):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    rv.definition({"erp.toml": f'[erp]\ntype = "postgres"\nmax_age = "1h"\n[erp.connection]\n'
                               f'url = "{rv.source_url}"\n[erp.tables]\n"public.t" = {{}}\n'})
    rv.target("update _rowvioli.meta set schema_version = 99")
    shape = rv.target(SHAPE)
    r = rv.run(*command, timeout=20)
    assert r.returncode != 0
    assert re.search(r"\b99\b", r.stderr) and re.search(r"\b4\b", r.stderr), r.stderr
    assert "init brings" not in r.stderr  # only an older target is brought up
    assert rv.target(SHAPE) == shape
    assert rv.target("select count(*) from _rowvioli.sources") == [(0,)]


@pytest.mark.parametrize("command", [["run"], ["work"]])
def test_a_version_3_target_is_refused_by_every_command_but_init_naming_both_versions(rv, command):
    rv.run("init")
    rv.run("key", "new")
    version_3(rv)
    r = rv.run(*command, timeout=20)
    assert r.returncode != 0
    assert "the target has schema version 3, this program works with version 4; rowvioli init brings it to 4" \
        in r.stderr, r.stderr


def test_the_control_connection_asks_postgres_to_notice_a_dead_worker_within_a_minute(rv, monkeypatch):
    # a worker machine that vanishes closes nothing; the server's own keepalive frees its locks (measured: 62 s)
    from rowvioli import target
    monkeypatch.setenv("ROWVIOLI_TARGET_URL", rv.target_url)
    conn = target.connect(init=True)
    names = ["tcp_keepalives_idle", "tcp_keepalives_interval", "tcp_keepalives_count", "tcp_user_timeout"]
    assert [target.sql(conn, f"SELECT current_setting('{n}')")[0][0] for n in names] == ["30", "10", "3", "60000"]
    conn.close()


def test_a_first_run_after_the_upgrade_ended_while_it_reads_the_change_log_under_two_keys_names_that_step(erp):
    """Ticket 14 of schema changes, item 6: the read takes about 0.6 s per million log rows (docs/measurements.md 16);
    a consumer who holds the change log stands in for a log large enough to outlast max_seconds."""
    table = '"public.customers" = {{ key = ["customer_no"], max_seconds = {} }}\n'
    ok(erp)
    erp.source("update customers set name = 'Anna2' where customer_no = 1")  # a U the other key never saw
    again(erp)
    erp.target(HAND)
    apply(erp, definition(erp, table.format(3)))  # the definition no longer tells
    released(erp)
    holder = psycopg.connect(erp.target_url)
    holder.execute("lock table raw_erp.customers__log in access exclusive mode")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    holder.close()
    assert reason.replace("***", "x") == (
        "ended after max_seconds = 3 while reading the change log raw_erp.customers__log under the definition's key "
        "and the primary key, to tell which of them wrote it; raise max_seconds once, until a run has told it")
    apply(erp, definition(erp, table.format(30)))
    again(erp)
    assert primary_key(erp) == ["customer_no"]
    log_replays(erp)


def test_a_change_log_from_before_the_upgrade_that_fits_neither_key_stops_with_the_statement_for_each(erp):
    """Ticket 11 left it untested, since 0.4.1 never wrote such a log itself: a person changed primary key and
    definition by hand and kept loading, so the log has rows under both keys (ticket 14 of schema changes)."""
    ok(erp)
    erp.target(HAND)
    apply(erp, elsewhere(erp))
    released(erp)
    # an I for a key that lives, under either key: written by hand, or under the other one
    erp.target("insert into raw_erp.customers__log select _run, 'I', _loaded_at + interval '1 s', customer_no, name, "
               "city from raw_erp.customers__log where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp).replace("***", "x")  # the source's password is x
    assert reason.startswith("the primary key of raw_erp.customers is (customer_no, name), the definition's key is "
                             "(customer_no), and nothing in the target tells"), reason
    assert """'[{"key": ["customer_no"]}]'""" in reason and """'[{"key": ["customer_no", "name"]}]'""" in reason


WAITING = "select count(*) from pg_stat_activity where datname = current_database() and wait_event_type = 'Lock'"


def test_two_inits_at_once_both_end_as_on_a_ready_target(rv):
    """Init containers on several replicas: the one that comes second waits for the first and finds version 4."""
    rv.run("init")
    version_3(rv)
    with psycopg.connect(rv.target_url) as held:  # the first step waits here, so that both have started
        held.execute("lock table _rowvioli.runs in access exclusive mode")
        inits = [rv.start("init") for _ in range(2)]
        until(lambda: rv.target(WAITING)[0][0] == 2)
    out = [p.communicate(timeout=30) + (p.returncode,) for p in inits]
    assert [code for _, _, code in out] == [0, 0], out
    assert rv.target("select schema_version from _rowvioli.meta") == [(4,)]

def as_role(rv, role):
    return {"ROWVIOLI_TARGET_URL": rv.target_url.replace("postgres:x@", f"{role}:secret_o@")}


@pytest.fixture
def owner(rv):
    """A version 3 target whose bookkeeping a role of its own owns, as when that role ran the first init (roles
    belong to the cluster: a name of its own)."""
    db = rv.target_url.rsplit("/", 1)[1]
    role = f"owner_{db}"
    rv.target(f"create role {role} login password 'secret_o'")
    rv.target(f"grant create on database {db} to {role}")
    try:
        assert rv.run("init", env=as_role(rv, role)).returncode == 0
        version_3(rv)
        yield role
    finally:
        rv.target(f"drop owned by {role}")
        rv.target(f"drop role {role}")


def test_init_by_a_superuser_gives_the_new_objects_the_owner_of_the_bookkeeping(rv, owner):
    r = rv.run("init")
    assert r.returncode == 0, r.stderr
    assert rv.target("select relname, relowner::regrole::text from pg_class where relnamespace = "
                     "'_rowvioli'::regnamespace and relowner::regrole::text <> %s", [owner]) == []


def test_init_by_a_role_that_does_not_own_the_bookkeeping_names_the_owner(rv, owner):
    other = owner.replace("owner_", "other_")
    rv.target(f"create role {other} login password 'secret_o'")
    try:
        rv.target(f"grant all on schema _rowvioli to {other}; grant all on all tables in schema _rowvioli to {other}")
        r = rv.run("init", env=as_role(rv, other))
        assert r.returncode == 1
        assert r.stderr == (f"_rowvioli belongs to the role {owner}: run rowvioli init as {owner} or as a "
                            "superuser; nothing was changed\n"), r.stderr
        assert rv.target("select schema_version from _rowvioli.meta") == [(3,)]
    finally:
        rv.target(f"drop owned by {other}")
        rv.target(f"drop role {other}")

