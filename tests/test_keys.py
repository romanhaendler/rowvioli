"""Keys: compared as a set, a first key, another key, a key taken away, a primary key put back, and the history view
by stretches (spec tests, stage 4; the numbers are those of `.scratch/schema-changes/cases.md`)."""
import json
from datetime import datetime

from test_columns_go_and_come import log_replays
from test_history import LOADED_AT, MIRROR, again, at
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


def comment(rv, table="raw_erp.customers"):
    """The keys the change log was written under, as the comment on its column _op says them."""
    [(text,)] = rv.target("select col_description(%s::regclass, (select attnum from pg_attribute where attrelid = "
                          "%s::regclass and attname = '_op'))", [f"{table}__log"] * 2)
    return text and json.loads(text)


def test_C4_another_key_keeps_the_history_and_the_table_at_every_moment_before_and_after_it(erp):  # stories 18, 19
    ok(erp)
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    erp.source("update customers set name = 'Anna2' where customer_no = 1")  # a column of the new key, under the old
    moments.append((again(erp), rows(erp.target, MIRROR)))
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    erp.source("insert into customers values (4, 'Dora', 'Ulm')")
    seam = again(erp)
    moments.append((seam, rows(erp.target, MIRROR)))
    assert primary_key(erp) == ["customer_no", "name"]
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    # a D for every old row and an I for every new one, at the moment of the run
    assert rows(erp.target, f"select _op, customer_no, name, _loaded_at = %s from raw_erp.customers__log {THIS_RUN}"
                .replace("%s", f"'{seam.isoformat()}'")) == sorted(
        [("D", 1, "Anna2", True), ("D", 2, "Ben", True), ("D", 3, "Cleo", True), ("I", 1, "Anna2", True),
         ("I", 2, "Ben", True), ("I", 3, "Cleo", True), ("I", 4, "Dora", True)], key=repr)
    assert [k["key"] for k in comment(erp)] == [["customer_no"], ["customer_no", "name"]]
    assert datetime.fromisoformat(comment(erp)[1]["from"]) == seam
    assert erp.target(f'select _op, "column", "key", "by" from _rowvioli.columns__log {THIS_RUN}') == [
        ("U", "name", 2, "definition")]
    erp.source("update customers set name = 'Ben2' where customer_no = 2")  # under the new key a D and an I
    moments.append((again(erp), rows(erp.target, MIRROR)))
    assert erp.target(f"select _op, customer_no, name from raw_erp.customers__log {THIS_RUN} order by _op") == [
        ("D", 2, "Ben"), ("I", 2, "Ben2")]
    for moment, mirror in moments:
        assert at(erp, moment) == mirror, moment
    log_replays(erp)
