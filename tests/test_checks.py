"""Checks, schema changes, failure reasons and secrets (spec tests 12, 13, 15, 16, 17, 18)."""
import json
import time

import psycopg
import pytest

from test_run import apply, definition, erp, ok, rows, run  # noqa: F401 (erp is a fixture)



def failed(rv, *args):
    """`run` that must fail one table; returns its reason as answered, in the status and in `runs`."""
    code, answer = run(rv, *args)
    assert code == 1, answer
    [reason] = [a["reason"] for a in answer["tables"].values() if a["status"] == "failed"]
    [(status, in_status)] = rv.target("select status, reason from _rowvioli.status where status = 'failed'")
    assert in_status == reason
    assert rv.target("select status, reason from _rowvioli.runs order by run desc limit 1") == [("failed", reason)]
    return reason


MIRROR = "select * from raw_erp.customers"
# what a reason says of an object the source does not have (ticket 17, L2, G2)
MISSING = ("an object the statement reading {table} names does not exist (SQLSTATE {state}): the table itself, a "
           "column, or one a view of it reads; rowvioli list erp shows the tables, and a table renamed or moved in "
           "the source keeps its mirror and history when the definition names it anew and keeps its target_table")


@pytest.mark.parametrize("change, expected", [
    ("insert into customers values (4, 'Dora', null); alter table customers drop constraint customers_pkey;"
     " insert into customers values (1, 'Anna2', null)", 'a key combination of ("customer_no") occurs twice in the '
     "source: make it unique there, or give the table a key that identifies a row"),
    ("alter table customers drop constraint customers_pkey; alter table customers alter customer_no drop not null;"
     " insert into customers values (null, 'Nobody', null)", 'a key column of ("customer_no") is null in a row of the '
     "source: give it a value there, or give the table a key whose columns always have one"),
    ("delete from customers", "zero rows"),
    ("delete from customers where customer_no <> 1", "67 % of the rows would be deleted"),
    ("alter table customers alter customer_no type text", "column customer_no has changed its type from integer to "
     "text, a type of another family in the key, so a row before cannot be told from one after: give the table "
     "another target_table"),  # cases C8
    ("alter table customers add column _op text", "column _op is a name of the change log"),
    ("alter table customers add column _run int", "column _run is a name of the change log"),
])
def test_a_check_fails_the_run_and_leaves_the_mirror_unchanged(erp, change, expected):
    ok(erp)
    before = rows(erp.target, MIRROR)
    for statement in change.split("; "):
        erp.source(statement)
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert expected in failed(erp)
    assert rows(erp.target, MIRROR) == before


def test_another_key_that_does_not_identify_a_row_fails_the_run_and_leaves_the_mirror_unchanged(erp):  # story 22
    ok(erp)
    before = rows(erp.target, MIRROR)
    erp.source("insert into customers values (4, 'Anna', 'Ulm')")
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ('a key combination of ("name") occurs twice in the source: make it unique there, or give the '
                           "table a key that identifies a row")
    assert rows(erp.target, MIRROR) == before


def test_a_table_that_lost_its_key_in_the_definition_says_the_least_that_works_and_keeps_the_mirror(erp):
    ok(erp)  # ticket 17, E2: the reason told to drop the mirror too, which consumers read
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ("the change log raw_erp.customers__log exists and this run would not write to it (log = "
                           'false or no key): drop it with its history view (DROP TABLE "raw_erp"."customers__log" '
                           "CASCADE), or rename both with the mirror")
    erp.target('DROP TABLE "raw_erp"."customers__log" CASCADE')
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")


@pytest.mark.parametrize("table", ['{ key = ["customer_no"], log = false }', "{}"])
def test_a_change_log_this_run_would_not_write_is_told_before_a_column_gone_from_the_source(erp, table):
    ok(erp)  # ticket 15, P3: the stop for the column said to drop it, and doing so led into this stop
    apply(erp, definition(erp, f'"public.customers" = {table}\n'))
    erp.source("alter table customers drop column city")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert "and this run would not write to it" in reason
    # its way out, followed as it says, leads into no second stop: the column's drop is said with the change log's
    for way in ['DROP TABLE "raw_erp"."customers__log" CASCADE', 'ALTER TABLE "raw_erp"."customers" DROP COLUMN "city"']:
        assert way in reason, reason
        erp.target(way)
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("team, what", [
    ("create table raw_erp.customers__log (x int)", "change log"),
    ("create table raw_erp.customers__log (customer_no int, name text, city text)", "change log"),
    ("create view raw_erp.customers__log as select 1 as _run, 'I' as _op, 'epoch'::timestamptz as _loaded_at", "change log"),
    ("create table raw_erp.customers__history (x int)", "history view"),
    ("create view raw_erp.customers__history as select 1 as x", "history view")])
def test_a_table_or_view_of_the_team_named_like_the_change_log_or_history_view_is_never_taken_for_it(
        erp, team, what, mirror):  # ticket 17, M2
    erp.target("create schema raw_erp")
    if mirror:  # the program moves onto a table it did not create
        erp.target("create table raw_erp.customers (customer_no int primary key, name text, city text)")
    erp.target(team)
    name = team.split()[2]
    before = erp.target(f"select * from {name}")
    kind = "a table with the columns _run, _op and _loaded_at" if what == "change log" else \
        "a view with the columns _valid_from and _valid_to"
    assert failed(erp) == (f"{name} is not rowvioli's {what} ({kind}), so the run leaves it alone: rename it, or "
                           "give the table another target_table")
    assert erp.target(f"select * from {name}") == before


@pytest.mark.parametrize("table, name", [('"public.notes" = {}', "raw_erp.notes__history"),
                                         ('"public.customers" = { key = ["customer_no"], log = false }',
                                          "raw_erp.customers__history")])
def test_a_view_of_the_team_named_like_a_history_view_beside_a_table_without_a_change_log_is_no_stop(erp, table, name):
    erp.target("create schema raw_erp")  # review of ticket 17, M2: such a table has no history view, and 0.4.1 loaded
    erp.target(f"create view {name} as select 1 as x")
    apply(erp, definition(erp, table + "\n"))
    ok(erp)
    assert erp.target(f"select * from {name}") == [(1,)]


def test_a_new_source_column_appears_in_the_mirror_and_the_change_log_with_values(erp):
    ok(erp)
    erp.source("alter table customers add column phone text")
    erp.source("update customers set phone = '0228' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    # a row whose new column is null equals its mirror row, so only Anna changed
    assert erp.target("select _op, customer_no, name, phone from raw_erp.customers__log where _run = "
                      "(select max(run) from _rowvioli.runs)") == [("U", 1, "Anna", "0228")]


def test_a_new_column_waits_10s_for_a_reading_consumer_then_fails_and_loads_once_the_reader_is_done(erp):
    ok(erp)
    before = rows(erp.target, MIRROR)
    erp.source("alter table customers add column phone text")
    erp.target("update _rowvioli.tables set requested_at = now()")
    with psycopg.connect(erp.target_url) as consumer:  # a long read: its transaction holds the mirror
        consumer.execute(MIRROR)
        started = time.monotonic()
        reason = failed(erp)
        # asked without waiting, as for every change of columns (story 43)
        assert reason.startswith("raw_erp.customers, its change log or its history view stayed in use for 10 s, so "
                                 "its columns could not change") and time.monotonic() - started >= 10, reason
    assert rows(erp.target, MIRROR) == before
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")


def test_a_table_without_a_key_fails_when_it_would_shrink_by_more_than_max_delete_share(erp):
    apply(erp, definition(erp, '"public.notes" = {}\n'))
    ok(erp)
    before = rows(erp.target, "select * from raw_erp.notes")
    erp.source("delete from notes where txt = 'a'")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "67 % of the rows would be deleted" in failed(erp)
    assert rows(erp.target, "select * from raw_erp.notes") == before


def test_max_delete_share_of_a_table_overrides_the_sources(erp):
    text = definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 0.9 }\n')
    apply(erp, text.replace('max_age = "1h"', 'max_age = "1h"\nmax_delete_share = 0.1'))
    ok(erp)
    erp.source("delete from customers where customer_no <> 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    code, answer = run(erp)
    assert code == 0, answer
    assert answer["tables"]["raw_erp.customers"]["deleted"] == 2



def test_an_unknown_connector_type_fails_with_a_reason_naming_the_type_and_the_worker(erp):
    apply(erp, definition(erp).replace('type = "postgres"', 'type = "nosuch"'))
    reason = failed(erp)
    [(worker,)] = erp.target("select worker from _rowvioli.runs")
    assert "nosuch" in reason and worker in reason



def test_a_worker_with_the_wrong_private_key_fails_the_run_with_a_reason(erp):
    (erp.dir / "worker.key").rename(erp.dir / "old.key")
    (erp.dir / "worker.pub").rename(erp.dir / "old.pub")
    assert erp.run("key", "new").returncode == 0  # the connection stays sealed for old.pub
    reason = failed(erp)
    [(worker,)] = erp.target("select worker from _rowvioli.runs")
    assert "decrypt" in reason and worker in reason


PASSWORD, WRONG = "Sesam-0815-oeffne-dich", "Falsch-4711-geheim"


@pytest.fixture
def secret(erp):
    """erp reading the source as a role whose password is a placeholder, plus a second source crm."""
    role = "reader_" + erp.source_url.rsplit("/", 1)[1]
    erp.source(f"create role {role} login password '{PASSWORD}'")
    erp.source(f"grant select on all tables in schema public to {role}")
    url = erp.source_url.replace("postgres:harness-pw-7@", f"{role}:$ERP_PASSWORD@")
    text = definition(erp).replace(erp.source_url, url)
    erp.definition({"erp.toml": text, "crm.toml": text.replace("[erp", "[crm")})
    return erp


def apply_with(rv, password):
    r = rv.run("apply", "sources", env={"ERP_PASSWORD": password})
    assert r.returncode == 0, r.stderr
    return r


def leaks(rv, password, *outputs):
    """Every place a user sees text: reasons in the status and in `runs`, and the output of commands."""
    seen = [r.stdout + r.stderr for r in outputs]
    seen += [str(x) for x in rv.target("select reason from _rowvioli.tables union all select reason from _rowvioli.runs")]
    return [s for s in seen if password in s]



def test_the_stored_connection_does_not_contain_the_password(secret):
    apply_with(secret, PASSWORD)
    assert secret.target("select count(*) from _rowvioli.sources where position(convert_to(%s, 'UTF8') in connection) > 0",
                         [PASSWORD]) == [(0,)]



def test_a_ciphertext_copied_to_another_source_is_rejected(secret):
    apply_with(secret, PASSWORD)
    secret.target("update _rowvioli.sources set connection = (select connection from _rowvioli.sources where name = 'erp')"
                  " where name = 'crm'")
    assert "another source" in failed(secret, "crm")
    assert run(secret, "erp")[0] == 0


def test_two_sources_whose_sealed_connections_are_swapped_both_fail(secret):
    apply_with(secret, PASSWORD)
    secret.target("update _rowvioli.sources set connection = case name when 'erp' then (select connection from"
                  " _rowvioli.sources where name = 'crm') else (select connection from _rowvioli.sources"
                  " where name = 'erp') end")
    code, answer = run(secret)
    assert code == 1
    assert [a["reason"].count("sealed for another source") for a in answer["tables"].values()] == [1, 1]



def test_the_password_appears_nowhere_when_a_run_fails(secret):
    out = [apply_with(secret, PASSWORD)]
    apply_with(secret, PASSWORD)
    secret.definition({"erp.toml": (secret.dir / "sources" / "erp.toml").read_text()
                       .replace('"public.customers"', '"public.missing"')})
    out.append(apply_with(secret, PASSWORD))
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    assert leaks(secret, PASSWORD, *out) == []



def test_the_password_appears_nowhere_when_the_source_refuses_the_login(secret):
    out = [apply_with(secret, WRONG), secret.run("run", "erp")]
    assert out[-1].returncode == 1
    [(reason,)] = secret.target("select reason from _rowvioli.runs")
    assert "password authentication failed" in reason
    # ticket 17, L1: a person fixes the variable and runs again, and meets the same reason
    assert reason.endswith("; the connection is the one the last apply stored: after changing a variable it reads, "
                           "run apply again"), reason
    assert leaks(secret, WRONG, *out) == []



def test_a_password_with_at_and_percent_written_plainly_loads_and_leaks_nowhere_when_refused(secret):
    plain = "Sesam@Torweg%zz-0815"
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{plain}'")
    out = [apply_with(secret, plain), secret.run("run", "erp")]
    assert out[-1].returncode == 0, out[-1].stdout + out[-1].stderr
    secret.source(f"alter role {role} password '{WRONG}'")
    secret.target("update _rowvioli.tables set requested_at = now()")
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    reason = secret.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert "password authentication failed" in reason
    for part in (plain, "Sesam", "Torweg", "zz-0815", "Sesam%40Torweg%25zz-0815"):
        assert leaks(secret, part, *out) == [], part


def test_a_password_from_a_variable_with_at_slash_and_colon_is_encoded_and_loads(secret):
    odd = "Se@sam/Tor:weg-0815"
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{odd}'")
    apply_with(secret, odd)
    assert run(secret, "erp")[0] == 0


@pytest.mark.parametrize("plain", ["Sesam[Torweg-0815", "Sesam]Torweg[0815"])
def test_a_password_with_a_bracket_written_plainly_gets_as_far_as_the_connection_and_leaks_nowhere(secret, plain):
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{plain}'")
    text = (secret.dir / "sources" / "erp.toml").read_text().replace("$ERP_PASSWORD", plain)
    secret.definition({"erp.toml": text, "crm.toml": text.replace("[erp", "[crm")})
    out = [secret.run("apply", "sources")]
    assert out[-1].returncode == 0, out[-1].stderr
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 0, out[-1].stdout + out[-1].stderr
    secret.source(f"alter role {role} password '{WRONG}'")
    secret.target("update _rowvioli.tables set requested_at = now()")
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    reason = secret.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert "password authentication failed" in reason
    for part in (plain, "Sesam", "Torweg"):
        assert leaks(secret, part, *out) == [], part


def test_a_new_empty_source_table_is_mirrored_as_an_empty_table(erp):
    erp.source("create table fresh (id int primary key, note text)")
    apply(erp, definition(erp, '"public.fresh" = { key = ["id"] }\n'))
    code, answer = run(erp)
    assert code == 0, answer
    assert erp.target("select count(*) from raw_erp.fresh") == [(0,)]


def test_an_option_postgres_does_not_know_fails_the_run_and_names_it(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], incremental = "updated" }\n'))
    assert failed(erp) == ("public.customers: the option incremental is not one of the postgres connector's; "
                           "it knows no option")


def test_an_emptied_source_publishes_when_max_delete_share_is_1(erp):
    ok(erp)
    erp.source("delete from customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "_delete_share = 1.0" in failed(erp)  # not "max_": the source's password is "x"
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 1.0 }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == []
    assert erp.target("select _op, count(*) from raw_erp.customers__log where _run = (select max(run) from "
                      "_rowvioli.runs) group by 1") == [("D", 3)]


def test_a_table_without_a_key_is_emptied_the_same_way(erp):
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    ok(erp)
    erp.source("delete from customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "_delete_share = 1.0" in failed(erp)
    apply(erp, definition(erp, '"public.customers" = { max_delete_share = 1.0 }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == []


@pytest.mark.parametrize("value, column, state", [
    ('my "secret": value', "n::int", "22P02"), ("3000000000", "n::int", "22003"),
    # Postgres's own messages that show the value unquoted or as a name: date field value out of range: 2000-13-01,
    # relation "3000000000" does not exist
    ("3000000000", "make_date(2000, length(n) + 3, 1)", "22008"),
    # a syntax error of a row's value, which Postgres quotes in class 42 too: syntax error in tsquery: "my secret 4711",
    # syntax error at or near "4711", improper relation name (too many dotted names): a.b.c.secret.e, invalid name
    # syntax; of class 42 only a missing right is shown
    ("my secret 4711", "to_tsquery(n)", "42601"), ("secret 3000000000", "n::regtype::text", "42601"),
    ("a.b.c.secret.e", "n::regclass", "42601"), ('"secret 3000000000', "n::regclass", "42602"),
    # and in other classes: invalid configuration parameter name "…", could not open file "…", cross-database
    # references are not implemented: …; so a message is shown by an allowlist of codes, not of classes
    ("secret.3000000000", "set_config(n, 'x', true)", "42602"), ("secret 3000000000", "pg_read_file(n)", "58P01"),
    ("a.secret.3000000000", "n::regclass", "0A000"),
    ("my secret\n4711", "to_tsquery(n)", "42601")])  # a line break inside the value
def test_a_value_in_the_sources_message_is_withheld_by_its_sqlstate(erp, value, column, state):  # decision 54, item 8
    erp.source("create table texts (k int, n text)")
    erp.source("insert into texts values (1, %s)", [value])
    erp.source(f"create view quoting as select k, {column} as n from texts")
    apply(erp, definition(erp, '"public.quoting" = {}\n'))
    reason = failed(erp)
    assert reason == (f"a statement raised an error (SQLSTATE {state}) in the source, reading public.quoting; its "
                      "message may hold a row's values, so it is left out here: the source's server log or a trace has it"), reason
    assert "secret" not in reason and "3000000000" not in reason and "2000-13" not in reason


def test_an_object_a_rows_value_names_that_does_not_exist_is_said_without_the_value(erp):  # ticket 17, L2
    erp.source("create table texts (k int, n text)")
    erp.source("insert into texts values (1, '3000000000')")
    erp.source("create view quoting as select k, n::regclass as n from texts")  # relation "3000000000" does not exist
    apply(erp, definition(erp, '"public.quoting" = {}\n'))
    reason = failed(erp)
    assert reason == MISSING.format(table="public.quoting", state="42P01") and "3000000000" not in reason


@pytest.mark.parametrize("where", ["target", "source"])
def test_a_statement_timeout_that_ends_a_run_is_named_with_the_way_out(erp, where):  # ticket 15, I2
    erp.source("create view many as select g as id from generate_series(1, 2000000) g")
    apply(erp, definition(erp, '"public.many" = { key = ["id"] }\n'))
    db = getattr(erp, f"{where}_url").rsplit("/", 1)[1]
    getattr(erp, where)(f"alter role postgres in database {db} set statement_timeout = '300ms'")
    assert failed(erp) == (
        "canceling statement due to statement timeout: the statement_timeout of the role in the " + where + " ended it; "
        "to let a run take longer, ALTER ROLE <its role> IN DATABASE <its database> SET statement_timeout = 0")


def test_a_name_postgres_quotes_in_its_message_stays_in_the_reason(erp):
    ok(erp)
    erp.target("alter table raw_erp.customers add constraint c check (name <> 'Anna2')")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.endswith('new row for relation "customers" violates check constraint "c"'), reason


def withheld(rv):
    """A run that fails one table on a message a consumer wrote; returns the reason, after making sure that the row's
    values are in none of the answer, the lines, the status and `runs`."""
    r = rv.run("run")
    assert r.returncode == 1, r.stdout
    [reason] = [a["reason"] for a in json.loads(r.stdout)["tables"].values()]
    assert rv.target("select reason from _rowvioli.status") == rv.target(
        "select reason from _rowvioli.runs order by run desc limit 1") == [(reason,)]
    assert "Anna2" not in r.stdout + r.stderr and "Secret" not in r.stdout + r.stderr, r.stdout + r.stderr
    return reason


@pytest.mark.parametrize("statement, sqlstate", [
    ("raise exception 'bad row %', NEW", "P0001"),
    ("raise exception using message = 'bad row ' || NEW::text, errcode = 'check_violation'", "23514"),
    ("assert NEW.name <> 'Anna2', 'bad row ' || NEW::text", "P0004"),
    # not raised by the code but by Postgres inside it, with the row's value: whatever the language, a message under
    # a consumer's function is withheld
    ("execute format('select from %I', NEW.name)", "42P01"),  # relation "Anna2" does not exist
    ("perform 1 / (length(NEW.name) - 5)", "22012"),
    # in the words of Postgres's own message of a constraint (ticket 15, X2)
    ("""raise exception 'new row for relation "customers" violates check constraint "%"', NEW.name""", "P0001"),
    ("""raise exception using message = format('duplicate key value violates unique constraint "%s"', NEW.name), """
     "errcode = 'unique_violation'", "23505")])
def test_a_message_a_consumers_trigger_raises_on_the_target_is_withheld_and_the_reason_names_the_function(
        erp, statement, sqlstate):
    ok(erp)
    erp.target(f"create function public.guard() returns trigger language plpgsql as $$ begin {statement}; return NEW;"
               " end $$")
    erp.target("create trigger g before insert or update on raw_erp.customers for each row execute function public.guard()")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert withheld(erp) == (f"function guard() raised an error (SQLSTATE {sqlstate}) in the target; its message may "
                             "hold a row's values, so it is left out here: the target's server log has it")


def test_a_message_from_a_consumers_function_in_c_that_names_no_frame_is_withheld_while_publishing(erp):
    ok(erp)  # make_date is C: its message has the value its arguments make of the row, and no frame says whose it is
    erp.target("alter table raw_erp.customers add constraint c check (make_date(2000, length(name) + 8, 1) < now())")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = withheld(erp)
    assert reason == ("a statement raised an error (SQLSTATE 22008) in the target; its message may hold a row's values, "
                      "so it is left out here: the target's server log has it"), reason


def test_an_object_a_cast_of_a_rows_value_does_not_find_is_withheld_while_publishing(erp):
    ok(erp)  # ::regclass names the value it did not find, and no frame says whose code cast it
    erp.target("alter table raw_erp.customers add constraint c check (name not like '%2' or name::regclass is not null)")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = withheld(erp)
    assert reason == ("a statement raised an error (SQLSTATE 42P01) in the target; its message may hold a row's values, "
                      "so it is left out here: the target's server log has it"), reason


@pytest.mark.parametrize("statement", ["raise exception 'bad name Secret %', n",
                                       "execute format('select from %I', 'Secret' || n)"])
def test_a_message_a_function_in_a_source_view_raises_is_withheld(erp, statement):
    erp.source("create function check_name(n text) returns text language plpgsql as $$ begin "
               f"if n = 'Anna' then {statement}; end if; return n; end $$")
    erp.source("create view checked as select customer_no, check_name(name) as name from customers")
    apply(erp, definition(erp, '"public.checked" = { key = ["customer_no"] }\n'))
    state = "P0001" if "raise" in statement else "42P01"
    assert withheld(erp) == (f"function check_name(text) raised an error (SQLSTATE {state}) in the source, reading "
                             "public.checked; its message may hold a row's values, so it is left out here: the "
                             "source's server log or a trace has it")


@pytest.mark.parametrize("constraint, change, says", [
    ("add constraint u unique (city)", "city = 'Essen'", 'duplicate key value violates unique constraint "u"'),
    ("add constraint f foreign key (city) references public.cities", "city = 'Ulm'",
     'violates foreign key constraint "f"'),
    ("alter name set not null", "name = null",
     'null value in column "name" of relation "customers" violates not-null constraint')])
def test_postgres_own_constraint_messages_keep_their_names(erp, constraint, change, says):
    ok(erp)
    erp.target("create table public.cities (city text primary key); insert into public.cities values ('Bonn'), ('Essen')")
    erp.target(f"alter table raw_erp.customers {constraint}")
    erp.source(f"update customers set {change} where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert says in failed(erp)  # a unique constraint's with the way out (review of ticket 17)


ORDERS = "create schema reporting; create table reporting.orders (id int, customer_no int references raw_erp.customers{})"


@pytest.mark.parametrize("action", ["", " on delete cascade", " on delete set null"])
def test_a_consumers_foreign_key_onto_the_mirror_keeps_its_rows_when_a_row_it_refers_to_is_updated(erp, action):
    ok(erp)  # ticket 17, M1: an update was a delete and an insert, which the key refused, cascaded or set null
    erp.target(ORDERS.format(action) + "; insert into reporting.orders values (1, 1)")
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert erp.target("select * from reporting.orders") == [(1, 1)]
    assert erp.target("select city from raw_erp.customers where customer_no = 1") == [("Köln",)]


def test_a_row_the_source_deleted_that_a_consumers_foreign_key_refers_to_stops_with_the_way_out(erp):  # ticket 17, M1
    ok(erp)
    erp.target(ORDERS.format("") + "; insert into reporting.orders values (1, 1)")
    erp.source("delete from customers where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        'update or delete on table "customers" violates foreign key constraint "orders_customer_no_fkey" on table '
        '"orders"' + REFERS.format('"orders"'))
    erp.target("delete from reporting.orders")  # the way out
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)


REFERS = (": the source deleted a row that table {0} refers to, or changed the value it refers to; delete the rows "
          "there that refer to it, or give the constraint ON DELETE CASCADE or ON DELETE SET NULL (ON UPDATE CASCADE "
          "for a changed value)")


def test_a_value_the_source_changed_that_a_consumers_foreign_key_refers_to_is_not_called_a_deleted_row(erp):
    ok(erp)  # review of ticket 17: a foreign key onto a unique column of the mirror that is not its key
    erp.target("alter table raw_erp.customers add constraint city_u unique (city); create schema reporting; "
               "create table reporting.visits (city text references raw_erp.customers (city)); "
               "insert into reporting.visits values ('Bonn')")
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ('update or delete on table "customers" violates foreign key constraint "visits_city_fkey" '
                           'on table "visits"' + REFERS.format('"visits"'))
    erp.target("alter table reporting.visits drop constraint visits_city_fkey, add foreign key (city) references "
               "raw_erp.customers (city) on update cascade")  # the way out
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert erp.target("select city from reporting.visits") == [("Köln",)]


def test_values_two_rows_swap_stop_on_a_consumers_unique_index_with_the_way_out_and_no_value(erp):
    ok(erp)  # review of ticket 17, M1: an update in place meets a unique index row by row, a delete and insert did not
    erp.target("create unique index city_u on raw_erp.customers (city)")
    erp.source("update customers set city = case customer_no when 1 then 'Essen' else 'Bonn' end "
               "where customer_no in (1, 2)")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        'duplicate key value violates unique constraint "city_u": Postgres checks a unique index on the mirror row by '
        "row, so it refuses a value that moves from one row to another within a run, as well as one the source holds "
        "twice; drop it, or put in its place a constraint that Postgres checks at the end of the statement: ALTER TABLE "
        "<the mirror> ADD UNIQUE (<its columns>) DEFERRABLE")
    erp.target("drop index raw_erp.city_u; alter table raw_erp.customers add unique (city) deferrable")  # the way out
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    from test_columns_go_and_come import log_replays  # here: that module imports this one
    log_replays(erp)


def test_a_source_table_created_anew_with_other_columns_says_what_it_may_be_and_the_setting_for_one_run(erp):  # H2
    ok(erp)
    erp.source("drop table customers; create table customers (customer_no int primary key, label text);"
               "insert into customers values (7, 'a'), (8, 'b'), (9, 'c')")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        "100 % of the rows would be deleted, more than max_delete_share = 0.5 allows: the source table may have been "
        "replaced or emptied; if so, max_delete_share = 1.0 on the table lets one run through")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 1.0 }\n'))
    ok(erp, "erp")
    assert rows(erp.target, MIRROR) == [(7, "a"), (8, "b"), (9, "c")]


CHILD = "select * from public.branch order by customer_no"
BRANCH = ("create table public.branch () inherits (raw_erp.customers);"
          "insert into public.branch values (7, 'Gus', 'Ulm'), (8, 'Hal', 'Ulm'), (9, 'Ida', 'Ulm'), (10, 'Jo', 'Ulm')")


def test_a_consumers_table_that_inherits_from_the_mirror_keeps_its_rows_and_is_not_read_as_the_mirror(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], log = false }\n'))
    ok(erp)
    erp.target(BRANCH)
    branch = erp.target(CHILD)
    apply(erp, definition(erp))  # the change log begins with the mirror's rows, not the child's
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    assert run(erp, "erp")[1]["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 0, "updated": 1,
                                                                 "deleted": 0}
    erp.source("update customers set city = 'Bonn' where customer_no = 1")
    assert run(erp, "erp")[1]["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 0, "updated": 1,
                                                                 "deleted": 0}
    assert erp.target(CHILD) == branch
    assert rows(erp.target, "select customer_no from only raw_erp.customers") == [(1,), (2,), (3,)]
    assert erp.target("select _op, customer_no from raw_erp.customers__log order by _run, customer_no") == [
        ("I", 1), ("I", 2), ("I", 3), ("U", 1)]


def test_a_consumers_table_that_inherits_from_the_mirror_keeps_its_rows_when_the_key_changes(erp):
    ok(erp)
    erp.target(BRANCH + ";create table public.notes () inherits (raw_erp.customers__log);"
               "insert into public.notes values (0, 'I', now(), 7, 'Gus', 'Ulm')")
    branch = erp.target(CHILD)
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    assert run(erp, "erp")[1]["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 3, "updated": 0,
                                                                 "deleted": 3}
    assert erp.target(CHILD) == branch
    assert erp.target("select count(*) from only raw_erp.customers__log "
                      "where _run = (select max(run) from _rowvioli.runs)") == [(6,)]
    # the history view reads the change log, not a consumer's table that inherits from it
    assert rows(erp.target, "select customer_no from raw_erp.customers__history where _valid_to is null") == [
        (1,), (2,), (3,)]

# a function that raises with a row's value, in a language whose frames Postgres names otherwise than PL/pgSQL's
RAISES = {"plperl": ("""elog(ERROR, "bad row $_TD->{new}{name}"); return;""",
                     """elog(ERROR, "bad name Secret$_[0]") if $_[0] eq 'Anna'; return $_[0];"""),
          "plpython3u": ("""plpy.error("bad row " + TD["new"]["name"])""",
                         """if n == "Anna": plpy.error("bad name Secret" + n)\nreturn n""")}
PL = ("the test image has PL/Perl's and PL/Python's libraries but not perl and python3: start two postgres:16-alpine "
      "containers, in both `apk add perl python3 && ln -s /usr/lib/perl5/core_perl/CORE/libperl.so /usr/lib/`, and run "
      "with ROWVIOLI_TEST_SERVERS=<source container>,<target container>")


def language(query, name):
    try:
        query(f"create extension {name}")
    except psycopg.Error:
        pytest.skip(PL)


@pytest.mark.parametrize("name", RAISES)
def test_a_message_a_consumers_trigger_in_pl_perl_or_pl_python_raises_is_withheld(erp, name):  # ticket 14, item 8
    language(erp.target, name)
    ok(erp)
    erp.target(f"create function public.guard() returns trigger language {name} as $${RAISES[name][0]}$$")
    erp.target("create trigger g before insert or update on raw_erp.customers for each row execute function public.guard()")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    state = {"plperl": "38000", "plpython3u": "XX000"}[name]  # external_routine_exception, internal_error
    assert withheld(erp) == (f'function "guard" raised an error (SQLSTATE {state}) in the target; its message may '
                             "hold a row's values, so it is left out here: the target's server log has it")


@pytest.mark.parametrize("name", RAISES)
def test_a_message_a_function_in_pl_perl_or_pl_python_in_a_source_view_raises_is_withheld(erp, name):
    language(erp.source, name)
    erp.source(f"create function check_name(n text) returns text language {name} as $${RAISES[name][1]}$$")
    erp.source("create view checked as select customer_no, check_name(name) as name from customers")
    apply(erp, definition(erp, '"public.checked" = { key = ["customer_no"] }\n'))
    assert withheld(erp) == ('function "check_name" raised an error in the source; its message may hold a row\'s '
                             "values, so it is left out here: the source's server log or a trace has it")
