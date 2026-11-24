"""Keys: compared as a set, a first key, another key, a key taken away, a primary key put back, and the history view
by stretches (spec tests, stage 4; the numbers are those of `.scratch/schema-changes/cases.md`)."""
from test_columns_go_and_come import log_replays
from test_history import again
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)

PRIMARY_KEY = ("select a.attname from pg_index i, unnest(i.indkey) with ordinality k(attnum, n), pg_attribute a "
               "where i.indrelid = %s::regclass and i.indisprimary and a.attrelid = i.indrelid and a.attnum = k.attnum "
               "order by k.n")
THIS_RUN = "where _run = (select max(run) from _rowvioli.runs)"


def primary_key(rv, table="raw_erp.customers"):
    return [k for (k,) in rv.target(PRIMARY_KEY, [table])]


def lines(rv, key):
    rv.source("create table lines (order_no int, line_no int, item text, primary key (order_no, line_no))")
    rv.source("insert into lines values (1, 1, 'a'), (1, 2, 'b'), (2, 1, 'c')")
    apply(rv, definition(rv, f'"public.lines" = {{ key = {key} }}\n'))
    ok(rv)


def test_C6_the_same_key_columns_in_another_order_are_the_same_key(erp):
    lines(erp, '["order_no", "line_no"]')
    apply(erp, definition(erp, '"public.lines" = { key = ["line_no", "order_no"] }\n'))
    erp.source("update lines set item = 'B' where order_no = 1 and line_no = 2")
    again(erp)
    assert primary_key(erp, "raw_erp.lines") == ["order_no", "line_no"]
    assert erp.target(f"select _op, order_no, line_no, item from raw_erp.lines__log {THIS_RUN}") == [("U", 1, 2, "B")]
    log_replays(erp, "raw_erp.lines")
