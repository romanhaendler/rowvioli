"""A numeric keeps its precision and scale, and a target column's own precision and scale are taken over (ticket 14)."""
from test_checks import failed
from test_run import apply, column_types, definition, erp, ok, run  # noqa: F401 (erp is a fixture)

UNCHANGED = {"status": "ok", "inserted": 0, "updated": 0, "deleted": 0}
HOLDS = "column price holds a value that its type numeric({}) in raw_erp.prices{} does not hold"


def prices(rv, columns, values):
    rv.source(f"create table prices (id int primary key, {columns})")
    rv.source(f"insert into prices values {values}")
    apply(rv, definition(rv, '"public.prices" = { key = ["id"] }\n'))


def test_a_new_mirror_has_the_sources_precision_and_scale_and_a_second_run_finds_no_change(erp):
    prices(erp, "a numeric(12, 2), b numeric(38, 10), c numeric(50, 5), d numeric, e numeric(5, 0), f numeric(5, -2),"
                " g numeric(3, 5)",
           "(1, 137.00, 1.5, 123.45, 1.10, 5, 12345, 0.00123), (2, null, null, null, null, null, null, null),"
           " (3, -0.01, 1234567890123456789012345678.0123456789, 123456789012345678901234567890123456789012345.12345,"
           " 0.000000000000000000000000000001, 99999, -99900, -0.00999)")
    ok(erp)
    # beyond Arrow's 38 digits, unconstrained (the driver's decimal256), and with a scale outside 0 to the precision,
    # which a target before Postgres 15 cannot hold, it stays numeric
    assert column_types(erp, "raw_erp.prices") == [("id", "integer"), ("a", "numeric(12,2)"), ("b", "numeric(38,10)"),
                                                   ("c", "numeric"), ("d", "numeric"), ("e", "numeric(5,0)"),
                                                   ("f", "numeric"), ("g", "numeric")]
    assert column_types(erp, "raw_erp.prices__log")[3:] == column_types(erp, "raw_erp.prices")
    text = "select id, a::text, b::text, e::text, f::text, g::text from {} order by id"
    assert erp.target(text.format("raw_erp.prices")) == erp.source(text.format("prices"))
    assert erp.target(text.format("raw_erp.prices"))[0] == (1, "137.00", "1.5000000000", "5", "12300", "0.00123")
    assert erp.target("select id, c, d from raw_erp.prices order by id") == erp.source(
        "select id, c, d from prices order by id")
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == UNCHANGED


def test_an_existing_numeric_10_2_table_with_a_view_takes_an_unconstrained_numeric_whose_values_fit(erp):
    prices(erp, "price numeric", "(1, 137), (2, 1.5), (3, null)")
    erp.target("create schema raw_erp; create table raw_erp.prices (id int primary key, price numeric(10, 2));"
               "create view public.priced as select * from raw_erp.prices")
    ok(erp)
    assert column_types(erp, "raw_erp.prices") == [("id", "integer"), ("price", "numeric(10,2)")]
    assert erp.target("select id, price::text from raw_erp.prices order by id") == [
        (1, "137.00"), (2, "1.50"), (3, None)]
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == UNCHANGED
    erp.source("update prices set price = 2.25 where id = 2")
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == {**UNCHANGED, "updated": 1}
    assert erp.target("select price::text from public.priced where id = 2") == [("2.25",)]


def test_a_value_the_target_column_cannot_hold_fails_naming_the_column_and_its_type(erp):
    prices(erp, "price numeric", "(1, 137)")
    erp.target("create schema raw_erp; create table raw_erp.prices (id int primary key, price numeric(10, 2))")
    ok(erp)
    erp.source("insert into prices values (2, 1.005)")
    assert failed(erp, "erp") == HOLDS.format("10,2", "") + " (1.005)"
    erp.source("update prices set price = 123456789 where id = 2")
    assert failed(erp, "erp").startswith(HOLDS.format("10,2", ""))
    assert erp.target("select id, price::text from raw_erp.prices") == [(1, "137.00")]


def test_a_mirror_made_by_0_1_0_with_numeric_keeps_loading_and_its_type(erp):
    prices(erp, "price numeric(12, 2)", "(1, 137.00), (2, 1.50)")
    ok(erp)
    # as 0.1.0 made them: numeric without precision, the driver's trailing zeros gone; the view goes with the ALTER
    erp.target("drop view raw_erp.prices__history; alter table raw_erp.prices alter price type numeric;"
               "alter table raw_erp.prices__log alter price type numeric;"
               "update raw_erp.prices set price = trim_scale(price);"
               "update raw_erp.prices__log set price = trim_scale(price)")
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == UNCHANGED
    assert column_types(erp, "raw_erp.prices") == [("id", "integer"), ("price", "numeric")]
    erp.source("update prices set price = 2.25 where id = 2")
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == {**UNCHANGED, "updated": 1}
    assert erp.target("select price from raw_erp.prices__history where id = 2 order by _valid_from") == \
        erp.target("select price from raw_erp.prices__log where id = 2 order by _run")


def test_a_wider_scale_in_the_source_loads_while_the_values_fit_and_the_readme_recipe_carries_it(erp):
    prices(erp, "price numeric(12, 2)", "(1, 137.00)")
    ok(erp)
    erp.source("alter table prices alter price type numeric(12, 4)")
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == UNCHANGED
    erp.source("insert into prices values (2, 1.2345)")
    assert failed(erp, "erp") == HOLDS.format("12,2", "") + " (1.2345)"
    # the recipe in docs/loading.md "What a person does by hand": the history view is created anew by the next run
    erp.target("drop view raw_erp.prices__history; alter table raw_erp.prices alter price type numeric(12, 4);"
               "alter table raw_erp.prices__log alter price type numeric(12, 4)")
    assert run(erp, "erp")[1]["tables"]["raw_erp.prices"] == {**UNCHANGED, "inserted": 1}
    assert erp.target("select price::text from raw_erp.prices__history where id = 2") == [("1.2345",)]


def test_a_change_log_narrower_than_its_mirror_fails_instead_of_rounding(erp):
    prices(erp, "price numeric(12, 4)", "(1, 1.25)")
    ok(erp)
    # half the recipe: the mirror was altered, the change log not
    erp.target("drop view raw_erp.prices__history; alter table raw_erp.prices__log alter price type numeric(12, 2)")
    erp.source("update prices set price = 1.2345")
    assert failed(erp, "erp") == HOLDS.format("12,2", "__log") + " (1.2345)"


def test_a_real_change_of_type_is_still_caught(erp):
    prices(erp, "price numeric(12, 2)", "(1, 137.00)")
    ok(erp)
    erp.source("alter table prices alter price type integer")
    assert failed(erp, "erp") == "column price has changed its type from numeric(12,2) to integer"
