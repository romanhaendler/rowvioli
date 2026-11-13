"""A table says where it lives: `target_schema` and `target_table` at a table (spec tests 1, 2, 3, 6, 7, 9)."""
import pytest
from test_run import SOURCE, apply, definition, ok, rows, run

CUSTOMERS = '"public.customers" = { key = ["customer_no"] }\n'


@pytest.fixture
def erp(rv):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    for statement in SOURCE.strip().split(";\n"):
        rv.source(statement)
    return rv


def test_a_table_is_loaded_where_the_definition_says_and_the_schema_is_created(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], target_schema = "hr",'
                               ' target_table = "staff" }\n"public.notes" = { target_table = "memos" }\n'))
    code, answer = run(erp)
    assert code == 0, answer
    assert set(answer["tables"]) == {"hr.staff", "raw_erp.memos"}
    assert rows(erp.target, "select * from hr.staff") == rows(erp.source, "select * from customers")
    assert erp.target("select count(*) from raw_erp.memos") == [(3,)]
    assert erp.target("select to_regclass('hr.staff__log') is not null") == [(True,)]
    assert erp.target("select target_table from _rowvioli.status order by 1") == [("hr.staff",), ("raw_erp.memos",)]


def test_two_tables_with_the_same_last_name_part_load_side_by_side_with_a_target_table(erp):
    erp.source("create schema sales; create table sales.customers (id int primary key)")
    erp.source("insert into sales.customers values (9)")
    apply(erp, definition(erp, CUSTOMERS + '"sales.customers" = { key = ["id"], target_table = "sales_customers" }\n'))
    ok(erp)
    assert erp.target("select count(*) from raw_erp.customers") == [(3,)]
    assert erp.target("select * from raw_erp.sales_customers") == [(9,)]


def test_two_sources_share_one_target_schema(erp):
    other = definition(erp, '"public.notes" = {}\n').replace("[erp", "[crm")
    erp.definition({"erp.toml": definition(erp, CUSTOMERS).replace("max_age", 'target_schema = "raw"\nmax_age'),
                    "crm.toml": other.replace("max_age", 'target_schema = "raw"\nmax_age')})
    assert erp.run("apply", "sources").returncode == 0
    ok(erp)
    assert erp.target("select (select count(*) from raw.customers), (select count(*) from raw.notes)") == [(3, 3)]


def test_a_table_renamed_in_the_source_keeps_its_mirror_under_its_old_target_table(erp):
    apply(erp, definition(erp, CUSTOMERS))
    ok(erp)
    erp.source("alter table customers rename to clients")
    apply(erp, definition(erp, '"public.clients" = { key = ["customer_no"], target_table = "customers" }\n'))
    erp.source("update clients set city = 'Köln' where customer_no = 1")
    code, answer = run(erp)
    assert code == 0, answer
    assert answer["tables"] == {"raw_erp.customers": {"status": "ok", "inserted": 0, "updated": 1, "deleted": 0}}
    assert erp.target("select city, _valid_to is null from raw_erp.customers__history where customer_no = 1"
                      " order by _valid_from") == [("Bonn", False), ("Köln", True)]


def test_a_different_table_taking_over_a_name_fails_and_the_old_mirror_is_unchanged(erp):
    apply(erp, definition(erp, CUSTOMERS))
    ok(erp)
    before = rows(erp.target, "select * from raw_erp.customers")
    apply(erp, definition(erp, '"public.notes" = { target_table = "customers" }\n'))
    code, answer = run(erp)
    assert code != 0 and answer["tables"]["raw_erp.customers"]["status"] == "failed"
    assert rows(erp.target, "select * from raw_erp.customers") == before
