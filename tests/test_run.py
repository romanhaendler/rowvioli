"""`rowvioli run`: one table from the source to its mirror (spec tests 4 rest, 5, 6, 7, 8, 21)."""
import json

import pytest

pytestmark = pytest.mark.skip(reason="ticket 03: run")

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
    assert run(erp, "erp", "public.customers")[1]["tables"] == {}
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
