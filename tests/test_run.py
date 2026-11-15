"""`rowvioli run`: one table from the source to its mirror (spec tests 4 rest, 5, 6, 7, 8, 21)."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

SOURCE = """
create table customers (customer_no int primary key, name text, city text);
insert into customers values (1, 'Anna', 'Bonn'), (2, 'Ben', 'Essen'), (3, 'Cleo', null);
create table notes (txt text, n int);
insert into notes values ('a', 1), ('a', 1), ('b', null);
"""


def definition(rv, tables='"public.customers" = { key = ["customer_no"] }\n'):
    return f"""
[erp]
type = "postgres"
max_age = "1h"
[erp.connection]
url = "{rv.source_url}"
[erp.tables]
{tables}"""


@pytest.fixture
def erp(rv):
    """init, key, a source database with tables, and a definition with customers applied."""
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    for statement in SOURCE.strip().split(";\n"):
        rv.source(statement)
    apply(rv, definition(rv))
    return rv


def apply(rv, text):
    rv.definition({"erp.toml": text})
    r = rv.run("apply", "sources")
    assert r.returncode == 0, r.stderr


def run(rv, *args):
    """`rowvioli run`, returns (exit code, parsed JSON answer)."""
    r = rv.run("run", *args)
    assert r.stdout, r.stderr
    return r.returncode, json.loads(r.stdout)


def ok(rv, *args):
    code, answer = run(rv, *args)
    assert code == 0, answer


def rows(query, sql):
    return sorted(query(sql), key=repr)


def test_a_new_table_is_loaded_and_the_mirror_equals_the_source(erp):
    assert erp.target("select status, due_at <= now() from _rowvioli.status") == [("new", True)]
    code, answer = run(erp)
    assert code == 0
    assert answer["tables"] == {"raw_erp.customers": {"status": "ok", "inserted": 3, "updated": 0, "deleted": 0}}
    assert rows(erp.target, "select * from raw_erp.customers") == rows(erp.source, "select * from customers")
    assert erp.target("select status, attempts, reason from _rowvioli.status") == [("ok", 0, None)]


def test_a_second_run_reports_the_changes_and_the_change_log_holds_exactly_them(erp):
    ok(erp)
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.source("delete from customers where customer_no = 2")
    erp.source("insert into customers values (4, 'Dora', 'Bonn'), (5, 'Emil', null)")
    code, answer = run(erp, "erp")
    assert code == 0
    assert answer["tables"] == {"raw_erp.customers": {"status": "ok", "inserted": 2, "updated": 1, "deleted": 1}}
    assert rows(erp.target, "select * from raw_erp.customers") == rows(erp.source, "select * from customers")
    second = erp.target("select max(run) from _rowvioli.runs")[0][0]
    assert erp.target("select _op, customer_no, name, city from raw_erp.customers__log where _run = %s "
                      "order by customer_no", [second]) == [
        ("U", 1, "Anna", "Köln"), ("D", 2, "Ben", "Essen"), ("I", 4, "Dora", "Bonn"), ("I", 5, "Emil", None)]
    assert erp.target("select count(*) from raw_erp.customers__log") == [(3 + 4,)]


def test_runs_has_one_row_per_run_with_worker_times_status_and_counts(erp):
    ok(erp)
    erp.source("delete from customers where customer_no = 3")
    ok(erp, "erp", "public.customers")
    log = erp.target("""select worker, started_at <= finished_at, status, rows_read, inserted, updated, deleted, reason
                          from _rowvioli.runs order by run""")
    assert [r[1:] for r in log] == [(True, "ok", 3, 3, 0, 0, None), (True, "ok", 2, 0, 0, 1, None)]
    assert all(":" in worker for worker, *_ in log)
    assert erp.target("select status, attempts from _rowvioli.status") == [("ok", 0)]


NOTES = '"public.notes" = {}\n'


def test_a_table_without_a_key_is_replaced_as_a_whole_and_has_no_change_log(erp):
    apply(erp, definition(erp, NOTES))
    assert run(erp)[1]["tables"] == {"raw_erp.notes": {"status": "ok", "inserted": 3, "updated": 0, "deleted": 0}}
    erp.source("delete from notes where txt = 'a'")
    erp.source("insert into notes values ('c', 3)")
    assert run(erp, "erp")[1]["tables"] == {
        "raw_erp.notes": {"status": "ok", "inserted": 2, "updated": 0, "deleted": 3}}
    assert rows(erp.target, "select * from raw_erp.notes") == rows(erp.source, "select * from notes")
    assert erp.target("select to_regclass('raw_erp.notes__log')") == [(None,)]


def test_a_numeric_column_arrives_as_numeric_with_equal_values(erp):
    erp.source("create table prices (id int primary key, fixed numeric(12, 2), free numeric)")
    erp.source("insert into prices values (1, 12.34, 1.5), (2, -0.01, 123456789012345678901234567890.123),"
               " (3, null, null), (4, 9999999999.99, 0.000000000000000000000000000001)")
    apply(erp, definition(erp, '"public.prices" = { key = ["id"] }\n'))
    ok(erp)
    assert erp.target("""select attname, format_type(atttypid, atttypmod) from pg_attribute
                          where attrelid = 'raw_erp.prices'::regclass and attnum > 0 order by attnum""") == [
        ("id", "integer"), ("fixed", "numeric"), ("free", "numeric")]
    assert rows(erp.target, "select * from raw_erp.prices") == rows(erp.source, "select * from prices")
    # a second run with unchanged numbers finds no difference
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == {"status": "ok", "inserted": 0, "updated": 0,
                                                              "deleted": 0}


def column_types(rv, table):
    return rv.target("""select attname, format_type(atttypid, atttypmod) from pg_attribute
                         where attrelid = %s::regclass and attnum > 0 order by attnum""", [table])


FAITHFUL = {"b": "bytea", "u": "uuid", "ts": "timestamp without time zone", "tz": "timestamp with time zone",
            "d": "date", "t": "time without time zone", "i": "interval", "f": "double precision",
            "ints": "integer[]", "texts": "text[]", "uuids": "uuid[]", "tzs": "timestamp with time zone[]"}


def test_types_the_driver_carries_arrive_unchanged(erp):
    erp.source("create table plain (id int primary key, "
               + ", ".join(f"{c} {t}" for c, t in FAITHFUL.items()) + ")")
    erp.source(r"""insert into plain values (1, '\x00ff', gen_random_uuid(), '0001-01-01 12:00',
                   '2020-01-01 12:00+14', '2020-02-29', '23:59:59.999999', '1 mon 2 days 03:04:05', '-Infinity',
                   '{1,null}', '{a,"b c"}', array[gen_random_uuid()], '{2020-01-01 00:00+00}'),
                   (2, null, null, null, null, null, null, null, null, null, null, null, null)""")
    apply(erp, definition(erp, '"public.plain" = { key = ["id"] }\n'))
    ok(erp)
    assert column_types(erp, "raw_erp.plain") == [("id", "integer"), *FAITHFUL.items()]
    assert rows(erp.target, "select * from raw_erp.plain") == rows(erp.source, "select * from plain")
    assert run(erp, "erp")[1]["tables"]["raw_erp.plain"] == {"status": "ok", "inserted": 0, "updated": 0,
                                                             "deleted": 0}


def test_json_and_jsonb_arrive_as_jsonb_and_load_on_every_run(erp):
    erp.source("create table docs (id int primary key, j json, b jsonb, bs jsonb[])")
    erp.source("""insert into docs values (1, '{"a": 1}', '{"b": [1, 2]}', array['{}'::jsonb]), (2, null, null, null)""")
    apply(erp, definition(erp, '"public.docs" = { key = ["id"] }\n'))
    ok(erp)
    assert column_types(erp, "raw_erp.docs") == [("id", "integer"), ("j", "jsonb"), ("b", "jsonb"),
                                                ("bs", "jsonb[]")]
    erp.source("""update docs set b = '{"b": 3}' where id = 1""")
    assert run(erp, "erp")[1]["tables"]["raw_erp.docs"] == {"status": "ok", "inserted": 0, "updated": 1,
                                                            "deleted": 0}
    assert rows(erp.target, "select id, j::text, b::text, bs::text from raw_erp.docs") == rows(
        erp.source, "select id, j::jsonb::text, b::text, bs::text from docs")


TEXT_TYPES = {"ip": "inet", "x": "xml", "t": "timetz", "r": "int4range", "bits": "bit(3)", "p": "point",
              "v": "tsvector", "ips": "inet[]"}


def test_types_the_driver_would_deliver_as_bytes_arrive_as_text_and_load_on_every_run(erp):
    erp.source("create table odd (id int primary key, "
               + ", ".join(f"{c} {t}" for c, t in TEXT_TYPES.items()) + ")")
    erp.source("""insert into odd values (1, '10.0.0.1/8', '<a>b</a>', '12:00+02', '[1,5)', B'101', '(1,2)',
                  'a fat cat', '{10.0.0.1,::1}'), (2, null, null, null, null, null, null, null, null)""")
    apply(erp, definition(erp, '"public.odd" = { key = ["id"] }\n'))
    ok(erp)
    assert column_types(erp, "raw_erp.odd") == [("id", "integer")] + [
        (c, "text") for c in TEXT_TYPES]
    erp.source("update odd set ip = '10.0.0.2' where id = 1")
    assert run(erp, "erp")[1]["tables"]["raw_erp.odd"] == {"status": "ok", "inserted": 0, "updated": 1,
                                                           "deleted": 0}
    cols = ", ".join(f"{c}::text" for c in TEXT_TYPES)
    assert rows(erp.target, f"select id, {cols} from raw_erp.odd") == rows(erp.source, f"select id, {cols} from odd")


def test_money_arrives_as_numeric_with_its_amount_and_loads_on_every_run(erp):
    erp.source("create table fees (id int primary key, m money, ms money[])")
    erp.source("insert into fees values (1, '12.50', '{1.05,-3}'), (2, null, null)")
    apply(erp, definition(erp, '"public.fees" = { key = ["id"] }\n'))
    ok(erp)
    assert column_types(erp, "raw_erp.fees") == [("id", "integer"), ("m", "numeric"), ("ms", "text[]")]
    assert rows(erp.target, "select id, m, ms::numeric[] from raw_erp.fees") == [
        (1, Decimal("12.50"), [Decimal("1.05"), Decimal("-3.00")]), (2, None, None)]
    assert run(erp, "erp")[1]["tables"]["raw_erp.fees"] == {"status": "ok", "inserted": 0, "updated": 0,
                                                            "deleted": 0}


def test_a_mirror_with_a_json_column_from_before_fails_naming_the_column_and_stays(erp):
    erp.source("""create table docs (id int primary key, j json); insert into docs values (1, '{"a": 1}')""")
    apply(erp, definition(erp, '"public.docs" = { key = ["id"] }\n'))
    ok(erp)
    erp.target("alter table raw_erp.docs alter j type json")  # as the wheel 0.2.0 left it
    assert run(erp, "erp")[0] == 1
    assert erp.target("select reason from _rowvioli.status") == [
        ("column j has changed its type from json to jsonb",)]
    assert erp.target("select j::text from raw_erp.docs") == [('{"a": 1}',)]


def test_run_exits_1_when_a_table_fails_and_names_every_table_it_touched(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"] }\n' + NOTES
                          + '"public.missing" = { key = ["id"] }\n'))
    code, answer = run(erp)
    assert code == 1
    assert set(answer["tables"]) == {"raw_erp.customers", "raw_erp.notes", "raw_erp.missing"}
    assert answer["tables"]["raw_erp.customers"]["status"] == "ok"
    failed = answer["tables"]["raw_erp.missing"]
    assert failed["status"] == "failed" and "missing" in failed["reason"]
    assert isinstance(answer["seconds"], float)
    assert erp.target("select status, reason is not null from _rowvioli.status where source_table = 'public.missing'"
                      ) == [("failed", True)]
    assert erp.target("select r.status, r.reason is not null from _rowvioli.runs r join _rowvioli.tables t "
                      "on t.id = r.table where t.source_table = 'public.missing'") == [("failed", True)]
    assert erp.target("select to_regclass('raw_erp.missing')") == [(None,)]


def test_run_ends_with_0_and_does_nothing_when_nothing_is_due(erp):
    ok(erp)
    code, answer = run(erp)
    assert (code, answer["tables"]) == (0, {})
    assert erp.target("select count(*) from _rowvioli.runs") == [(1,)]


def test_a_fresh_table_with_a_load_time_after_its_last_run_is_loaded_once(erp):
    ok(erp)
    erp.target("update _rowvioli.tables set loaded_at = now() - interval '30 minutes',"
               " attempted_at = now() - interval '30 minutes'")
    assert run(erp)[1]["tables"] == {}  # fresh by its maximum age
    passed = datetime.now(timezone.utc) - timedelta(minutes=10)
    apply(erp, definition(erp, f'"public.customers" = {{ key = ["customer_no"], at = ["{passed:%H:%M}"], '
                               'timezone = "UTC" }\n'))
    erp.source("insert into customers values (9, 'Ida', 'Ulm')")
    code, answer = run(erp)
    assert code == 0
    assert answer["tables"] == {"raw_erp.customers": {"status": "ok", "inserted": 1, "updated": 0, "deleted": 0}}
    assert run(erp)[1]["tables"] == {}
    assert erp.target("select count(*) from _rowvioli.runs") == [(2,)]


def test_run_source_table_loads_a_table_that_is_not_due(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"] }\n' + NOTES))
    ok(erp)
    erp.source("insert into customers values (9, 'Ida', 'Ulm')")
    code, answer = run(erp, "erp", "public.customers")
    assert code == 0 and list(answer["tables"]) == ["raw_erp.customers"]
    assert answer["tables"]["raw_erp.customers"]["inserted"] == 1
    assert erp.target("select source_table, count(*) from _rowvioli.runs r join _rowvioli.tables t "
                      "on t.id = r.table group by 1 order by 1") == [("public.customers", 2), ("public.notes", 1)]


def test_a_disabled_table_is_not_loaded_again_and_its_mirror_stays(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"] }\n' + NOTES))
    ok(erp)
    apply(erp, definition(erp, NOTES))
    erp.target("update _rowvioli.tables set requested_at = now()")  # even a request does not load it
    code, answer = run(erp)
    assert code == 0 and list(answer["tables"]) == ["raw_erp.notes"]
    r = erp.run("run", "erp", "public.customers")
    assert r.returncode == 1 and "public.customers" in r.stderr
    assert erp.target("select count(*) from _rowvioli.runs r join _rowvioli.tables t on t.id = r.table "
                      "where t.source_table = 'public.customers'") == [(1,)]
    assert rows(erp.target, "select * from raw_erp.customers") == rows(erp.source, "select * from customers")


def test_a_source_with_reordered_columns_still_gives_a_correct_mirror_and_change_log(erp):
    ok(erp)
    # same names and types, the two text columns swapped
    erp.source("create table c2 (customer_no int primary key, city text, name text)")
    erp.source("insert into c2 select customer_no, city, name from customers")
    erp.source("drop table customers")
    erp.source("alter table c2 rename to customers")
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.source("insert into customers values (4, 'Bonn', 'Dora')")
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, "select customer_no, name, city from raw_erp.customers") == rows(
        erp.source, "select customer_no, name, city from customers")
    second = erp.target("select max(run) from _rowvioli.runs")[0][0]
    assert erp.target("select _op, customer_no, name, city from raw_erp.customers__log where _run = %s "
                      "order by customer_no", [second]) == [("U", 1, "Anna", "Köln"), ("I", 4, "Dora", "Bonn")]


@pytest.mark.parametrize("command", ["run", "work"])
@pytest.mark.parametrize("variable", ["ROWVIOLI_TARGET_URL", "ROWVIOLI_KEY_FILE"])
def test_run_and_work_name_a_missing_variable_at_start(rv, command, variable):
    r = rv.run(command, env={variable: ""}, timeout=10)
    assert r.returncode != 0 and variable in r.stderr


@pytest.mark.parametrize("command", ["init", "status", "run", "work"])
def test_an_unreachable_target_gives_the_drivers_message_without_password_or_traceback(rv, command):
    r = rv.run(command, env={"ROWVIOLI_TARGET_URL": "postgresql://u:pass%25word@127.0.0.1:1/db"}, timeout=10)
    assert r.returncode == 1 and "Failed to connect" in r.stderr and "Traceback" not in r.stderr, r.stderr
    # libpq quotes a password that is not valid percent-encoding in its message
    r = rv.run(command, env={"ROWVIOLI_TARGET_URL": "postgresql://u:geheim%zz@127.0.0.1:1/db"}, timeout=10)
    assert r.returncode == 1 and "invalid percent-encoded token" in r.stderr and "geheim" not in r.stderr, r.stderr


@pytest.mark.parametrize("command", ["run", "work"])
def test_run_and_work_refuse_fewer_than_one_slot(rv, command):
    # with no slot nothing can start, so `run` would wait forever for what is due
    r = rv.run(command, "--slots", "0", timeout=10)
    assert r.returncode == 2 and "--slots must be at least 1" in r.stderr


@pytest.mark.parametrize("name", [("erp", "public.nosuch"), ("nosuch", "public.customers"), ("erp", "public.notes"),
                                  ("nosuch",)])
def test_run_with_an_unknown_or_disabled_name_exits_1_and_loads_nothing(erp, name):
    apply(erp, definition(erp, NOTES))
    apply(erp, definition(erp))  # notes disabled, customers due
    r = erp.run("run", *name)
    assert r.returncode == 1 and " ".join(name) in r.stderr
    assert erp.target("select count(*) from _rowvioli.runs") == [(0,)]


def test_log_false_gives_no_change_log(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], log = false }\n'))
    ok(erp)
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    assert run(erp, "erp")[1]["tables"] == {
        "raw_erp.customers": {"status": "ok", "inserted": 0, "updated": 1, "deleted": 0}}
    assert rows(erp.target, "select * from raw_erp.customers") == rows(erp.source, "select * from customers")
    assert erp.target("select to_regclass('raw_erp.customers__log')") == [(None,)]


def test_a_composite_key_mirrors_and_logs_correctly(erp):
    erp.source("create table lines (order_no int, line_no int, item text, primary key (order_no, line_no))")
    erp.source("insert into lines values (1, 1, 'a'), (1, 2, 'b'), (2, 1, 'c')")
    apply(erp, definition(erp, '"public.lines" = { key = ["order_no", "line_no"] }\n'))
    ok(erp)
    erp.source("update lines set item = 'B' where order_no = 1 and line_no = 2")
    erp.source("delete from lines where order_no = 2 and line_no = 1")
    # each new row shares one key column with a row that is there or was there
    erp.source("insert into lines values (2, 2, 'd'), (3, 1, 'a')")
    assert run(erp, "erp")[1]["tables"] == {
        "raw_erp.lines": {"status": "ok", "inserted": 2, "updated": 1, "deleted": 1}}
    assert rows(erp.target, "select * from raw_erp.lines") == rows(erp.source, "select * from lines")
    second = erp.target("select max(run) from _rowvioli.runs")[0][0]
    assert erp.target("select _op, order_no, line_no, item from raw_erp.lines__log where _run = %s "
                      "order by order_no, line_no", [second]) == [
        ("U", 1, 2, "B"), ("D", 2, 1, "c"), ("I", 2, 2, "d"), ("I", 3, 1, "a")]


def test_every_run_carries_the_hash_of_the_definition_applied_before_it(erp):
    ok(erp)
    first = erp.target("select definition from _rowvioli.meta")[0][0]
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_age = "2h" }\n'))
    second = erp.target("select definition from _rowvioli.meta")[0][0]
    ok(erp, "erp")
    assert erp.target("select definition from _rowvioli.runs order by run") == [(first,), (second,)]
    assert first and second and first != second


def test_run_says_start_and_end_on_stderr_and_stdout_stays_one_answer(erp):
    r = erp.run("run")
    assert json.loads(r.stdout)["tables"]["raw_erp.customers"]["status"] == "ok"
    assert "raw_erp.customers started, run 1" in r.stderr
    assert "raw_erp.customers ok after" in r.stderr and "started with" not in r.stderr
