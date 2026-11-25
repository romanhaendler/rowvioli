"""Keys: compared as a set, a first key, another key, a key taken away, a primary key put back, and the history view
by stretches (spec tests, stage 4; the numbers are those of `.scratch/schema-changes/cases.md`)."""
import json
from datetime import datetime

import pytest

from test_checks import failed
from test_columns_go_and_come import columns, log_replays
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
    assert erp.target(f'select "column", "key" from _rowvioli.columns__log {THIS_RUN}') == []  # the record neither


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


def test_C1_a_first_key_replaces_the_mirror_once_more_adds_the_primary_key_and_begins_the_change_log(erp):  # story 17
    apply(erp, definition(erp, '"public.notes" = {}\n'))
    ok(erp)
    assert erp.target("select count(*) from raw_erp.notes where txt = 'a'") == [(2,)]  # the old rows hold it twice
    erp.source("delete from notes; insert into notes values ('a', 1), ('b', 2)")
    apply(erp, definition(erp, '"public.notes" = { key = ["txt"] }\n'))
    again(erp)
    [(loaded_at,)] = erp.target("select loaded_at from _rowvioli.tables where target_table = 'notes'")
    assert primary_key(erp, "raw_erp.notes") == ["txt"]
    assert rows(erp.target, "select * from raw_erp.notes") == [("a", 1), ("b", 2)]
    assert erp.target("select _op, txt, n, _loaded_at from raw_erp.notes__log order by txt") == [
        ("I", "a", 1, loaded_at), ("I", "b", 2, loaded_at)]
    assert comment(erp, "raw_erp.notes") == [{"key": ["txt"]}]
    assert erp.target(f'select _op, "column", "key", "by" from _rowvioli.columns__log {THIS_RUN}') == [
        ("U", "txt", 1, "definition")]
    log_replays(erp, "raw_erp.notes")


NOT_NULL = ("select attname from pg_attribute where attrelid = %s::regclass and attnum > 0 and attnotnull "
            "order by attnum")
LOG_FALSE = '"public.customers" = { key = ["customer_no"], log = false }\n'


def test_C3_a_key_taken_away_without_a_change_log_drops_the_primary_key_and_its_not_null(erp):
    apply(erp, definition(erp, LOG_FALSE))
    ok(erp)
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    erp.source("alter table customers drop constraint customers_pkey, alter customer_no drop not null")
    erp.source("insert into customers values (1, 'Anna', 'Bonn'), (null, 'Nobody', null)")  # no key: twice is fine
    again(erp)
    assert primary_key(erp) == []
    assert erp.target(NOT_NULL, ["raw_erp.customers"]) == []
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    assert erp.target(f'select _op, "column", "key", "by" from _rowvioli.columns__log {THIS_RUN}') == [
        ("U", "customer_no", None, "definition")]


def test_C5_another_key_without_a_change_log_replaces_the_primary_key(erp):
    apply(erp, definition(erp, LOG_FALSE))
    ok(erp)
    apply(erp, definition(erp, '"public.customers" = { key = ["name"], log = false }\n'))
    again(erp)
    assert primary_key(erp) == ["name"]
    assert erp.target(NOT_NULL, ["raw_erp.customers"]) == [("name",)]
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    assert erp.target("select to_regclass('raw_erp.customers__log')") == [(None,)]


def test_C15_a_primary_key_changed_by_hand_is_put_back_and_recorded_by_hand(erp):  # story 24
    ok(erp)
    erp.target("alter table raw_erp.customers drop constraint customers_pkey, add primary key (customer_no, name)")
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    again(erp)
    assert primary_key(erp) == ["customer_no"]
    assert erp.target(NOT_NULL, ["raw_erp.customers"]) == [("customer_no",)]
    # the change log was written under the definition's key all along: only the row that changed
    assert erp.target(f"select _op, customer_no, city from raw_erp.customers__log {THIS_RUN}") == [("U", 1, "Köln")]
    assert comment(erp) == [{"key": ["customer_no"]}]
    assert erp.target(f'select _op, "column", "key", "by", note from _rowvioli.columns__log {THIS_RUN} '
                      'order by "column"') == [
        ("U", column, key, "hand", "the primary key (customer_no, name) was put back to the definition's (customer_no)")
        for column, key in [("customer_no", 1), ("name", None)]]
    log_replays(erp)


def test_a_primary_key_changed_by_hand_under_a_new_target_name_is_put_back_whatever_the_old_name_recorded(erp):
    ok(erp)  # ticket 15, B3: the old target name, which stays, recorded the key that the hand now set
    apply(erp, definition(erp, '"public.customers" = { key = ["name"], target_table = "clients" }\n'))
    again(erp)
    erp.target("alter table raw_erp.clients drop constraint clients_pkey, add primary key (customer_no)")
    again(erp)
    assert primary_key(erp, "raw_erp.clients") == ["name"]
    assert erp.target("select count(*) from raw_erp.clients__log " + THIS_RUN) == [(0,)]
    assert erp.target(f'select "column", "by" from _rowvioli.columns__log {THIS_RUN} order by 1') == [
        ("customer_no", "hand"), ("name", "hand")]


@pytest.mark.parametrize("consumer, named", [
    ("create table reporting.orders (id int, customer_no int references raw_erp.customers)",
     "constraint orders_customer_no_fkey on table reporting.orders depends on index raw_erp.customers_pkey"),
    ("create view reporting.names as select customer_no, name from raw_erp.customers group by customer_no",
     "view reporting.names depends on constraint customers_pkey on table raw_erp.customers"),
])
def test_C12_a_consumers_foreign_key_or_view_on_the_primary_key_stops_another_key_and_is_named(erp, consumer, named):
    ok(erp)  # story 23
    erp.target("create schema reporting")
    erp.target(consumer)
    before = rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.startswith("the key of raw_erp.customers would change from (customer_no) to (customer_no, name), "
                             f"but {named}"), reason
    assert (rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")) == before
    assert primary_key(erp) == ["customer_no"]


def test_a_publication_of_the_mirrors_deletes_stops_another_key_and_says_how_to_go_on(erp):  # ticket 15, C2
    ok(erp)
    erp.target("create publication feed for table raw_erp.customers")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        "the key of raw_erp.customers would change from (customer_no) to (customer_no, name), but publication feed "
        "publishes its updates and deletes, for which the primary key is its replica identity: give it another for "
        'the change, ALTER TABLE "raw_erp"."customers" REPLICA IDENTITY FULL: change or drop that, and the next run '
        "goes on")
    assert primary_key(erp) == ["customer_no"]
    erp.target('ALTER TABLE "raw_erp"."customers" REPLICA IDENTITY FULL')  # the way out
    again(erp)
    assert primary_key(erp) == ["customer_no", "name"]


def test_C12_a_consumers_foreign_key_on_a_key_column_that_leaves_the_key_is_named_with_a_view_in_the_way(erp):
    ok(erp)
    erp.target("create schema reporting; create table reporting.orders (id int, customer_no int references "
               "raw_erp.customers); create view reporting.cities as select city from raw_erp.customers")
    erp.source("alter table customers drop column city")
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason == (
        "the key of raw_erp.customers would change from (customer_no) to (name), but constraint orders_customer_no_fkey "
        "on table reporting.orders depends on index raw_erp.customers_pkey; and column city is gone from the source "
        "and would leave the mirror raw_erp.customers, but view reporting.cities depends on column city of table "
        "raw_erp.customers: change or drop that, and the next run goes on"), reason
    assert primary_key(erp) == ["customer_no"]


def test_C14_a_new_key_with_a_column_the_old_rows_of_the_change_log_lack_reads_each_stretch_by_its_own_key(erp):
    ok(erp)
    first = (erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))
    erp.source("alter table customers add column tenant text not null default 'a', drop constraint customers_pkey, "
               "add primary key (customer_no, tenant)")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "tenant"] }\n'))
    seam = again(erp)
    erp.source("insert into customers values (1, 'Anna', 'Bonn', 'b')")
    last = again(erp)
    assert primary_key(erp) == ["customer_no", "tenant"]
    assert at(erp, first[0]) == first[1]
    history = "select customer_no, tenant, _valid_from, _valid_to from raw_erp.customers__history order by 1, 3, 2"
    assert erp.target(history) == [(1, None, first[0], seam), (1, "a", seam, None), (1, "b", last, None),
                                   (2, None, first[0], seam), (2, "a", seam, None),
                                   (3, None, first[0], seam), (3, "a", seam, None)]
    log_replays(erp)


def test_C9_a_key_column_renamed_in_the_source_without_renamed_is_another_key_and_the_old_one_stays_in_the_log(erp):
    ok(erp)  # `renamed` in the definition, which makes it a rename, is ticket 06's
    first = erp.target(LOADED_AT)[0][0]
    erp.source("alter table customers rename column customer_no to id")
    apply(erp, definition(erp, '"public.customers" = { key = ["id"] }\n'))
    seam = again(erp)
    assert primary_key(erp) == ["id"]
    assert columns(erp) == ["name", "city", "id"]
    assert erp.target("select customer_no, id, _valid_from, _valid_to from raw_erp.customers__history "
                      "where name = 'Anna' order by _valid_from") == [(1, None, first, seam), (None, 1, seam, None)]
    assert [k["key"] for k in comment(erp)] == [["customer_no"], ["id"]]
    assert erp.target(f'select _op, "column", "key", mirror, "by" from _rowvioli.columns__log {THIS_RUN} '
                      'order by "column"') == [("U", "customer_no", None, False, "source"),
                                               ("I", "id", 1, True, "definition")]
    log_replays(erp)


def test_C13_a_key_value_that_changes_is_a_D_and_an_I(erp):
    ok(erp)
    erp.source("update customers set customer_no = 8 where customer_no = 1")
    again(erp)
    assert erp.target(f"select _op, customer_no, name from raw_erp.customers__log {THIS_RUN} order by _op") == [
        ("D", 1, "Anna"), ("I", 8, "Anna")]
    log_replays(erp)


ANOTHER_KEY = '"public.customers" = { key = ["customer_no", "name"] }\n'


@pytest.mark.parametrize("changed_key", [False, True])
def test_a_comment_on_op_that_names_another_key_than_the_change_logs_stops_with_the_text_to_put_back(erp, changed_key):
    ok(erp)  # ticket 15, X5: a comment of the right shape was trusted, and the history view partitioned by its key
    if changed_key:
        apply(erp, definition(erp, ANOTHER_KEY))
        again(erp)
    keys = comment(erp)
    erp.target("comment on column raw_erp.customers__log._op is "
               f"""'{json.dumps(keys[:-1] + [{**keys[-1], "key": ["city"]}])}'""")
    erp.source("alter table customers add column phone text")  # the history view is built anew
    erp.target("update _rowvioli.tables set requested_at = now()")
    put_back = f"""COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '{json.dumps(keys)}'"""
    assert failed(erp) == (
        "the comment on column _op of the change log raw_erp.customers__log, which says the keys it was written "
        f"under, names (city) last, where the change log is written under ({', '.join(keys[-1]['key'])}): the comment "
        "was changed, or the mirror's primary key was changed by hand to the definition's new key before a run changed "
        f"it; put it back, {put_back}")
    erp.target(put_back)
    again(erp)
    log_replays(erp)


@pytest.mark.parametrize("earlier", [False, True])
def test_a_primary_key_changed_by_hand_to_the_definitions_new_key_before_the_run_is_changed_as_the_definition_would(
        erp, earlier):
    ok(erp)  # tickets 17, M7, and 18: the stop gave the comment there already, or a key the log was not written under
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    if earlier:  # a change of key by the definition before
        apply(erp, definition(erp, ANOTHER_KEY))
        moments.append((again(erp), rows(erp.target, MIRROR)))
    erp.source("update customers set name = 'Bert' where customer_no = 2")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    [(pk,)] = erp.target("select conname from pg_constraint where conrelid = 'raw_erp.customers'::regclass and "
                         "contype = 'p'")
    erp.target(f"alter table raw_erp.customers drop constraint {pk}, add primary key (name)")
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.source("update customers set city = 'Kiel' where customer_no = 3")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    assert primary_key(erp) == ["name"]
    assert [k["key"] for k in comment(erp)] == [["customer_no"], *[["customer_no", "name"]] * earlier, ["name"]]
    log_replays(erp)
    for moment, mirror in moments:
        assert at(erp, moment) == mirror


def test_a_primary_key_changed_by_hand_to_a_third_key_while_the_definition_changes_it_changes_from_the_recorded_one(
        erp):
    erp.source("update customers set city = 'Kiel' where customer_no = 3")
    ok(erp)  # ticket 18, review: the stop said to write the hand's key into the comment, which the log was not written under
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    erp.target("alter table raw_erp.customers drop constraint customers_pkey, add primary key (city)")
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.source("update customers set city = 'Ulm' where customer_no = 2")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    erp.source("alter table customers drop constraint customers_pkey, alter customer_no drop not null")  # no key now
    erp.source("update customers set city = null, customer_no = null where customer_no = 1")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    assert primary_key(erp) == ["name"]
    assert [k["key"] for k in comment(erp)] == [["customer_no"], ["name"]]
    log_replays(erp)
    for moment, mirror in moments:
        assert at(erp, moment) == mirror


@pytest.mark.parametrize("removal", ["is null", "is 'our customers'", "a key no list", "a from no moment",
                                     "a column that does not exist"])
def test_the_comment_on_op_removed_after_a_change_of_key_stops_the_run_with_the_text_to_put_back(erp, removal):
    ok(erp)
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    keys = comment(erp)
    edited = {"a key no list": [{"key": "customer_no"}, keys[1]], "a from no moment": [keys[0], {**keys[1], "from": "x"}],
              "a column that does not exist": [{"key": ["i"]}, keys[1]]}  # as P18 edited it by hand
    erp.target("comment on column raw_erp.customers__log._op "
               + (f"is '{json.dumps(edited[removal])}'" if removal in edited else removal))
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    put_back = f"""COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '{json.dumps(keys)}'"""
    assert reason == ("the comment on column _op of the change log raw_erp.customers__log, which says the keys it was "
                      f"written under, is missing or unreadable, and the key has changed: put it back, {put_back}")
    erp.target(put_back)
    again(erp)
    assert comment(erp) == keys
    log_replays(erp)


def test_a_lost_comment_on_op_stops_the_run_when_the_change_logs_first_rows_are_those_of_the_run_that_noted_the_keys(erp):
    ok(erp)  # the note and the oldest row of the change log carry the same moment: the note counts
    erp.target("truncate raw_erp.customers__log")
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    keys = comment(erp)
    erp.target("comment on column raw_erp.customers__log._op is null")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ("the comment on column _op of the change log raw_erp.customers__log, which says the keys it "
                           "was written under, is missing or unreadable, and the key has changed: put it back, "
                           f"""COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '{json.dumps(keys)}'""")


@pytest.mark.parametrize("how", ["created again", "another target_table"])
def test_a_lost_comment_on_op_of_a_change_log_begun_after_a_change_of_key_is_no_stop(erp, how):
    ok(erp)  # ticket 17, V1: the text to put back was the note of an earlier change log under the same table
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    if how == "created again":
        erp.target("drop table raw_erp.customers__log cascade")
    else:
        apply(erp, definition(erp, ANOTHER_KEY.replace("}", ', target_table = "clients" }')))
    again(erp)  # a new change log under one key
    table = "clients" if how == "another target_table" else "customers"
    erp.target(f"comment on column raw_erp.{table}__log._op is null")
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    again(erp)
    log_replays(erp, f"raw_erp.{table}")


def test_a_lost_comment_on_op_back_under_an_earlier_target_name_gives_that_change_logs_keys_to_put_back(erp):
    ok(erp)  # ticket 18, item 4: a note of another target name's change log, newer than this one's first row
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    keys = comment(erp)
    apply(erp, definition(erp, ANOTHER_KEY.replace("}", ', target_table = "clients" }')))
    again(erp)
    apply(erp, definition(erp, '"public.customers" = { key = ["name"], target_table = "clients" }\n'))
    again(erp)
    apply(erp, definition(erp, ANOTHER_KEY))
    erp.target("comment on column raw_erp.customers__log._op is null")
    erp.target("update _rowvioli.tables set requested_at = now()")
    put_back = f"""COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '{json.dumps(keys)}'"""
    assert failed(erp).endswith(f"put it back, {put_back}")
    erp.target(put_back)
    again(erp)
    log_replays(erp)


def test_a_lost_comment_on_op_of_a_mirror_renamed_by_hand_gives_its_keys_to_put_back(erp):  # ticket 17, V1
    ok(erp)
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    keys = comment(erp)
    erp.target("alter table raw_erp.customers rename to clients; alter table raw_erp.customers__log rename to "
               "clients__log; alter view raw_erp.customers__history rename to clients__history")
    apply(erp, definition(erp, ANOTHER_KEY.replace("}", ', target_table = "clients" }')))
    erp.target("comment on column raw_erp.clients__log._op is null")
    erp.target("update _rowvioli.tables set requested_at = now()")
    put_back = f"""COMMENT ON COLUMN "raw_erp"."clients__log"._op IS '{json.dumps(keys)}'"""
    assert failed(erp) == ("the comment on column _op of the change log raw_erp.clients__log, which says the keys it "
                           f"was written under, is missing or unreadable, and the key has changed: put it back, {put_back}")
    erp.target(put_back)
    again(erp)
    log_replays(erp, "raw_erp.clients")


@pytest.mark.parametrize("earlier", [True, False])
def test_a_primary_key_changed_by_hand_to_the_new_key_of_a_mirror_renamed_by_hand_stops_with_the_old_key_to_put_back(
        erp, earlier):
    ok(erp)  # ticket 18, review: without a record under the new name the stop gave the comment there already
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    if earlier:  # a change of key by the definition, whose note gives the comment's text
        apply(erp, definition(erp, ANOTHER_KEY))
        moments.append((again(erp), rows(erp.target, MIRROR)))
    old = comment(erp)[-1]["key"]
    erp.target("alter table raw_erp.customers rename to clients; alter table raw_erp.customers__log rename to "
               "clients__log; alter view raw_erp.customers__history rename to clients__history")
    [(pk,)] = erp.target("select conname from pg_constraint where conrelid = 'raw_erp.clients'::regclass and "
                         "contype = 'p'")
    erp.target(f"alter table raw_erp.clients drop constraint {pk}, add constraint by_name primary key (name)")
    pk = "by_name"
    apply(erp, definition(erp, '"public.customers" = { key = ["name"], target_table = "clients" }\n'))
    erp.source("update customers set city = 'Kiel' where customer_no = 3")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    put_back = f'ALTER TABLE "raw_erp"."clients" DROP CONSTRAINT "{pk}", ADD PRIMARY KEY ({", ".join(f'"{c}"' for c in old)})'
    assert reason.endswith(put_back if earlier else f"or the old primary key, {put_back}"), reason
    erp.target(put_back)
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    moments.append((erp.target("select loaded_at from _rowvioli.tables")[0][0],
                    rows(erp.target, "select customer_no, name, city from raw_erp.clients")))
    assert primary_key(erp, "raw_erp.clients") == ["name"]
    log_replays(erp, "raw_erp.clients")
    for moment, mirror in moments:
        assert rows(lambda q: erp.target(q, [moment, moment]), "select customer_no, name, city from "
                    "raw_erp.clients__history where _valid_from <= %s and (_valid_to > %s or _valid_to is null)") \
            == mirror


def test_a_column_of_an_old_key_retired_in_the_change_log_is_renamed_in_the_comment_on_op_too(erp):  # decision 9
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    seam = again(erp)
    erp.source("alter table customers drop column customer_no")
    again(erp)
    erp.source("alter table customers add column customer_no text")
    erp.target("update _rowvioli.runs set program_version = '0.0.1'")  # the retirement is recorded by the reader
    again(erp)
    [(run,)] = erp.target("select max(run) from _rowvioli.runs")
    keys = comment(erp)
    assert [k["key"] for k in keys] == [[f"customer_no__{run}"], ["name"]]
    assert erp.target(f"select customer_no__{run}, _valid_from, _valid_to from raw_erp.customers__history "
                      "where name = 'Anna' order by _valid_from limit 1") == [(1, first, seam)]
    [(note,)] = erp.target(f'select note from _rowvioli.columns__log {THIS_RUN} and "column" = %s',
                           [f"customer_no__{run}"])
    assert note.endswith(f"the change log's keys: {json.dumps(keys)}")
    erp.target("comment on column raw_erp.customers__log._op is null")  # the text to put back is the renamed one
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).endswith(f"._op IS '{json.dumps(keys)}'")
    log_replays(erp)


# a change log of 0.4.1 has no comment on _op (ticket 15, B1: the old key was written with its name in the mirror)
@pytest.mark.parametrize("of_0_4_1", [False, True])
def test_a_column_of_the_old_key_retired_in_the_run_the_key_changes_keeps_its_values_and_frees_its_not_null(
        erp, of_0_4_1):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    if of_0_4_1:
        erp.target("comment on column raw_erp.customers__log._op is null")
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.source("alter table customers alter column customer_no type text")  # in the same run: goes and comes
    seam = again(erp)
    [(run,)] = erp.target("select max(run) from _rowvioli.runs")
    assert primary_key(erp) == ["name"]
    assert [k["key"] for k in comment(erp)] == [[f"customer_no__{run}"], ["name"]]
    erp.source("insert into customers values ('9', 'Zed', 'Ulm')")  # a row the retired column has no value for
    again(erp)
    assert erp.target(f"select customer_no__{run}, customer_no, _valid_from, _valid_to from raw_erp.customers__history "
                      "where name = 'Anna' order by _valid_from") == [(1, None, first, seam), (None, "1", seam, None)]
    log_replays(erp)


def test_mirror_change_log_and_history_view_renamed_by_hand_after_a_change_of_key_keep_the_history(erp):  # cases E6
    ok(erp)
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    apply(erp, definition(erp, ANOTHER_KEY))
    moments.append((again(erp), rows(erp.target, MIRROR)))
    for old, new in [("customers", "clients"), ("customers__log", "clients__log"),
                     ("customers__history", "clients__history")]:
        erp.target(f"alter {'view' if new.endswith('history') else 'table'} raw_erp.{old} rename to {new}")
    apply(erp, definition(erp, ANOTHER_KEY.replace(" }", ', target_table = "clients" }')))
    erp.source("alter table customers add column phone text")  # the history view is made anew from the comment
    erp.source("update customers set phone = '0228' where customer_no = 2")
    again(erp)
    for moment, mirror in moments:
        assert rows(lambda q: erp.target(q, [moment, moment]), "select customer_no, name, city from "
                    "raw_erp.clients__history where _valid_from <= %s and (_valid_to > %s or _valid_to is null)") \
            == mirror, moment
    log_replays(erp, "raw_erp.clients")


def test_C8_a_key_column_of_another_family_stops_the_run_and_changes_nothing(erp):  # story 22
    ok(erp)
    before = rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")
    erp.source("alter table customers alter customer_no type text")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).startswith("column customer_no ")
    assert (rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")) == before
    assert primary_key(erp) == ["customer_no"]


def test_two_changes_of_key_and_one_back_with_rows_and_a_column_that_go_give_the_table_at_every_moment(erp):
    erp.source("alter table customers add column phone text")
    ok(erp)
    moments = [(erp.target(LOADED_AT)[0][0], rows(erp.target, MIRROR))]
    apply(erp, definition(erp, ANOTHER_KEY))
    erp.source("alter table customers drop column phone")  # in the run of the change, with a row gone and one come
    erp.source("delete from customers where customer_no = 3; insert into customers values (4, 'Dora', 'Ulm')")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    erp.source("update customers set name = 'Ben2' where customer_no = 2")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.source("delete from customers where customer_no = 1")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    apply(erp, definition(erp))  # back to the first key
    erp.source("update customers set city = 'Köln' where customer_no = 2")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    erp.source("update customers set city = 'Kiel' where customer_no = 4")
    moments.append((again(erp), rows(erp.target, MIRROR)))
    assert primary_key(erp) == ["customer_no"]
    assert [k["key"] for k in comment(erp)] == [["customer_no"], ["customer_no", "name"], ["name"], ["customer_no"]]
    assert [datetime.fromisoformat(k["from"]) for k in comment(erp)[1:]] == [moments[i][0] for i in (1, 3, 4)]
    for moment, mirror in moments:
        assert at(erp, moment) == mirror, moment
    log_replays(erp)


def test_the_moments_in_the_comment_on_op_are_iso_8601_whatever_the_datestyle(erp, monkeypatch):
    ok(erp)
    apply(erp, definition(erp, ANOTHER_KEY))
    monkeypatch.setenv("PGOPTIONS", "-c datestyle=SQL,DMY")  # for the run only: the tests read timestamps in ISO
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    monkeypatch.delenv("PGOPTIONS")
    assert datetime.fromisoformat(comment(erp)[1]["from"]) == erp.target(LOADED_AT)[0][0]


def test_a_change_log_begun_anew_after_a_change_of_key_has_one_key_and_does_not_stop(erp):
    ok(erp)
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    apply(erp, definition(erp, ANOTHER_KEY.replace(" }", ", log = false }")))
    erp.target("drop table raw_erp.customers__log cascade")  # the way out the reason gives for log = false
    again(erp)
    apply(erp, definition(erp, ANOTHER_KEY))
    again(erp)
    assert comment(erp) == [{"key": ["customer_no", "name"]}]
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    again(erp)
    log_replays(erp)


def test_a_foreign_key_and_a_view_on_the_key_are_named_with_a_view_on_a_gone_column_in_one_reason(erp):  # ticket 14
    ok(erp)
    erp.target("create schema reporting; create table reporting.orders (id int, customer_no int references "
               "raw_erp.customers); create view reporting.names as select customer_no, name from raw_erp.customers "
               "group by customer_no; create view reporting.cities as select city from raw_erp.customers")
    erp.source("alter table customers drop column city")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    for named in ("constraint orders_customer_no_fkey on table reporting.orders depends on index "
                  "raw_erp.customers_pkey", "view reporting.names depends on constraint customers_pkey on table "
                  "raw_erp.customers", "view reporting.cities depends on column city of table raw_erp.customers"):
        assert named in reason, reason
    assert primary_key(erp) == ["customer_no"] and columns(erp) == ["customer_no", "name", "city"]
    erp.target("drop table reporting.orders; drop view reporting.names, reporting.cities")  # one round of work
    again(erp)
    assert primary_key(erp) == ["customer_no", "name"] and columns(erp) == ["customer_no", "name"]
    log_replays(erp)
