"""A rename: proven by the data or stated in the definition, renamed in mirror and change log with no row written
(spec tests, stage 5; the numbers are those of `.scratch/schema-changes/cases.md`)."""
import pytest

from test_checks import failed
from test_columns_go_and_come import columns, log_replays
from test_file import files, load as load_file  # noqa: F401 (files is a fixture)
from test_history import LOADED_AT, again
from test_keys import comment, primary_key
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)

PEOPLE = "raw_erp.people"
THIS_RUN = "where _run = (select max(run) from _rowvioli.runs)"
RECORD = f'select _op, "column", was, "by", note from _rowvioli.columns__log {THIS_RUN} order by "column"'


def people(rv, n=30, table='{ key = ["id"] }'):
    """A table of n people in six cities, a third of them members, loaded once."""
    rv.source("create table people (id int primary key, name text, city text, member boolean)")
    rv.source("insert into people select i, 'p' || i, (array['Bonn', 'Essen', 'Ulm', 'Kiel', 'Jena', 'Hof'])[i %% 6 + 1], "
              "i %% 3 = 0 from generate_series(1, %s) i", [n])
    apply(rv, definition(rv, f'"public.people" = {table}\n'))
    ok(rv)


def test_A24_a_rename_the_data_prove_is_renamed_in_mirror_and_change_log_and_no_row_is_written(erp):  # stories 25, 26
    people(erp)
    erp.target("create schema reporting")
    erp.target("create view reporting.cities as select id, city from raw_erp.people")
    attnums = erp.target("select attrelid::regclass::text, attnum from pg_attribute where attname = 'city' "
                         "and attrelid in ('raw_erp.people'::regclass, 'raw_erp.people__log'::regclass) order by 1")
    log = erp.target("select count(*) from raw_erp.people__log")
    erp.source("alter table people rename column city to town")
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "town", "member"]
    assert columns(erp, f"{PEOPLE}__log")[-2:] == ["town", "member"]
    assert erp.target("select attrelid::regclass::text, attnum from pg_attribute where attname = 'town' and attrelid "
                      "in ('raw_erp.people'::regclass, 'raw_erp.people__log'::regclass) order by 1") == attnums
    assert erp.target("select count(*) from raw_erp.people__log") == log
    # story 26: the consumer's view keeps working under its own column name
    assert erp.target("select attname from pg_attribute where attrelid = 'reporting.cities'::regclass "
                      "and attnum > 0") == [("id",), ("city",)]
    assert rows(erp.target, "select * from reporting.cities") == rows(erp.source, "select id, town from people")
    assert erp.target(RECORD) == [
        ("D", "city", None, "source", None),
        ("I", "town", "city", "source", "proven by the data: 30 rows unchanged otherwise, 30 of them equal, "
                                        "6 distinct values")]
    log_replays(erp, PEOPLE)


def gone_and_come(rv, old, new):
    """No rename: the old column left the mirror and stays in the change log, the new one came with a U per row."""
    assert old not in columns(rv, PEOPLE) and new in columns(rv, PEOPLE)
    assert old in columns(rv, f"{PEOPLE}__log")
    assert ("U", old, None, "source", None) in rv.target(RECORD)
    assert [r for r in rv.target(RECORD) if r[2]] == []  # no column has a was: nothing renamed
    assert rv.target(f"select count(*) > 0 from {PEOPLE}__log {THIS_RUN}") == [(True,)]
    log_replays(rv, PEOPLE)


@pytest.mark.parametrize("n, steps, old, new", [
    (30, ["alter table people rename column member to active"], "member", "active"),  # a flag: two values
    (19, ["alter table people rename column city to town"], "city", "town"),  # a small table
    (30, ["alter table people rename column city to town; alter table people add column place text; "
          "update people set place = town"], "city", "town"),  # two candidates
    (30, ["alter table people rename column city to town; update people set town = 'Bad' where id = 1"],
     "city", "town"),  # a row unchanged otherwise that differs (cases A25)
    (30, ["alter table people add column town text; update people set town = city",
          "alter table people drop column town", "alter table people rename column city to town"],
     "city", "town"),  # the new name is in the change log
    (30, ["alter table people add column place text; update people set place = city",
          "alter table people drop column place; alter table people rename column city to town"],
     "city", "town"),  # two gone columns for one new
])
def test_a_rename_is_not_assumed_where_the_data_do_not_prove_it(erp, n, steps, old, new):  # story 27
    people(erp, n)
    for step in steps:
        erp.source(step)
        again(erp)
    gone_and_come(erp, old, new)


def test_A24_twenty_rows_and_five_values_are_enough_for_a_proof(erp):
    people(erp, 20)
    erp.source("alter table people add column grade int; update people set grade = id % 5")
    again(erp)
    erp.source("alter table people rename column grade to level")
    again(erp)
    assert erp.target(RECORD) == [
        ("D", "grade", None, "source", None),
        ("I", "level", "grade", "source", "proven by the data: 20 rows unchanged otherwise, 20 of them equal, "
                                          "5 distinct values")]
    log_replays(erp, PEOPLE)


def test_A25_rows_changed_otherwise_in_the_same_interval_are_left_out_of_the_proof(erp):
    people(erp)
    erp.source("alter table people rename column city to town")
    erp.source("update people set name = name || '!', town = 'Bad' where id <= 5")
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "town", "member"]
    assert erp.target(f"select _op, count(*) from {PEOPLE}__log {THIS_RUN} group by _op") == [("U", 5)]
    assert erp.target(f'select note from _rowvioli.columns__log {THIS_RUN} and "column" = \'town\'') == [
        ("proven by the data: 25 rows unchanged otherwise, 25 of them equal, 6 distinct values",)]
    log_replays(erp, PEOPLE)


def test_A26_two_columns_renamed_in_one_run_are_each_proven(erp):
    people(erp)
    erp.source("alter table people rename column city to town")
    erp.source("alter table people rename column name to label")
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "label", "town", "member"]
    assert [r[:3] for r in erp.target(RECORD)] == [("D", "city", None), ("I", "label", "name"), ("D", "name", None),
                                                   ("I", "town", "city")]
    assert erp.target(f"select count(*) from {PEOPLE}__log {THIS_RUN}") == [(0,)]
    log_replays(erp, PEOPLE)


def test_a_table_without_a_key_proves_nothing_and_a_gone_column_stops_as_before(erp):
    people(erp, table="{}")
    erp.source("alter table people rename column city to town")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).startswith("column city is missing in the source")


TYPES = ("select attrelid::regclass::text, format_type(atttypid, atttypmod) from pg_attribute where attname = 'points' "
         "and attrelid in ('raw_erp.people'::regclass, 'raw_erp.people__log'::regclass) order by 1")


@pytest.mark.parametrize("wide", [False, True])
def test_A27_renamed_and_retyped_in_its_family_is_a_rename_and_the_type_goes_by_the_values(erp, wide):
    people(erp)
    erp.source("alter table people add column score integer; update people set score = id % 7")
    again(erp)
    erp.source("alter table people rename column score to points; alter table people alter points type bigint")
    if wide:  # a row changed otherwise is left out of the proof, and its value needs the wider type
        erp.source("update people set points = 5000000000, name = 'big' where id = 1")
    again(erp)
    assert columns(erp, PEOPLE)[-1] == "points" and "score" not in columns(erp, f"{PEOPLE}__log")
    assert erp.target(TYPES) == [("raw_erp.people", "bigint" if wide else "integer"),
                                 ("raw_erp.people__log", "bigint" if wide else "integer")]
    assert erp.target(f"select _op, id, points from {PEOPLE}__log {THIS_RUN}") == ([("U", 1, 5000000000)] if wide else [])
    log_replays(erp, PEOPLE)


def test_A27_renamed_into_another_family_is_a_drop_and_an_add(erp):
    people(erp)
    erp.source("alter table people add column score integer; update people set score = id % 7")
    again(erp)
    erp.source("alter table people rename column score to points; alter table people alter points type text")
    again(erp)
    gone_and_come(erp, "score", "points")


def test_A28_a_column_renamed_while_a_new_one_takes_its_old_name_is_not_seen_and_every_row_is_a_U(erp):
    people(erp)  # a known limit: the rows are right, only the history of two columns is joined wrongly
    erp.source("alter table people rename column city to town; alter table people add column city text; "
               "update people set city = upper(town)")
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "city", "member", "town"]
    assert rows(erp.target, f"select * from {PEOPLE}") == rows(erp.source, "select id, name, city, member, town "
                                                                           "from people")
    assert erp.target(f"select _op, count(*) from {PEOPLE}__log {THIS_RUN} group by _op") == [("U", 30)]
    assert [r[:2] for r in erp.target(RECORD)] == [("I", "town")]
    log_replays(erp, PEOPLE)


def test_A31_a_name_whose_case_alone_changes_is_another_name_and_proven_like_any(erp):
    people(erp)
    erp.source('alter table people rename column city to "City"')
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "City", "member"]
    assert erp.target(f"select count(*) from {PEOPLE}__log {THIS_RUN}") == [(0,)]
    assert [r[:3] for r in erp.target(RECORD)] == [("I", "City", "city"), ("D", "city", None)]
    log_replays(erp, PEOPLE)


def test_renamed_in_the_definition_makes_a_renamed_flag_a_rename(erp):  # story 28
    people(erp)
    erp.source("alter table people rename column member to active")
    apply(erp, definition(erp, '"public.people" = { key = ["id"], renamed = { active = "member" } }\n'))
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "city", "active"]
    assert erp.target(f"select count(*) from {PEOPLE}__log {THIS_RUN}") == [(0,)]
    assert erp.target(RECORD) == [("I", "active", "member", "definition", None),
                                  ("D", "member", None, "definition", None)]
    log_replays(erp, PEOPLE)


def test_A25_renamed_in_the_definition_is_a_rename_where_rows_differ_and_they_are_a_U(erp):
    people(erp)
    erp.source("alter table people rename column city to town; update people set town = 'Bad' where id = 1")
    apply(erp, definition(erp, '"public.people" = { key = ["id"], renamed = { town = "city" } }\n'))
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "town", "member"]
    assert erp.target(f"select _op, id, town from {PEOPLE}__log {THIS_RUN}") == [("U", 1, "Bad")]
    log_replays(erp, PEOPLE)


def test_C9_a_key_column_renamed_with_renamed_stays_the_key_and_the_comment_on_op_follows(erp):  # story 28
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    erp.source("alter table customers rename column customer_no to id")
    apply(erp, definition(erp, '"public.customers" = { key = ["id"], renamed = { id = "customer_no" } }\n'))
    erp.source("update customers set city = 'Köln' where id = 1")
    second = again(erp)
    assert primary_key(erp) == ["id"]
    assert columns(erp) == ["id", "name", "city"]
    assert erp.target("select _op, id, city from raw_erp.customers__log " + THIS_RUN) == [("U", 1, "Köln")]
    assert comment(erp) == [{"key": ["id"]}]
    assert erp.target("select city, _valid_from, _valid_to from raw_erp.customers__history where id = 1 "
                      "order by _valid_from") == [("Bonn", first, second), ("Köln", second, None)]
    assert erp.target(f'select _op, "column", "key", was, "by", note from _rowvioli.columns__log {THIS_RUN} '
                      'order by "column"') == [
        ("D", "customer_no", 1, None, "definition", None),
        ("I", "id", 1, "customer_no", "definition", 'the change log\'s keys: [{"key": ["id"]}]')]
    erp.target("comment on column raw_erp.customers__log._op is null")  # the text to put back is the renamed one
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).endswith("""._op IS '[{"key": ["id"]}]'""")
    log_replays(erp, "raw_erp.customers")


def test_C9_a_key_column_renamed_in_the_run_that_changes_the_key_keeps_its_was(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    erp.source("alter table customers rename column customer_no to id")
    apply(erp, definition(erp, '"public.customers" = { key = ["id", "name"], renamed = { id = "customer_no" } }\n'))
    second = again(erp)
    assert primary_key(erp) == ["id", "name"]
    assert [k["key"] for k in comment(erp)] == [["id"], ["id", "name"]]
    assert erp.target(f'select _op, "column", was from _rowvioli.columns__log {THIS_RUN} order by "column"') == [
        ("D", "customer_no", None), ("I", "id", "customer_no"), ("U", "name", None)]
    assert erp.target("select name, _valid_from, _valid_to from raw_erp.customers__history where id = 1 "
                      "order by _valid_from") == [("Anna", first, second), ("Anna", second, None)]
    log_replays(erp, "raw_erp.customers")


def test_a_key_column_of_another_family_stops_as_before_while_a_column_is_renamed(erp):
    ok(erp)
    erp.source("alter table customers alter customer_no type text; alter table customers rename column city to town")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.startswith("column customer_no has changed its type from integer to ") \
        and "a type of another family in the key" in reason, reason


def test_renamed_in_the_definition_renames_the_mirror_of_a_table_without_a_change_log(erp):
    people(erp, table='{ key = ["id"], log = false }')
    erp.source("alter table people rename column city to town")
    apply(erp, definition(erp, '"public.people" = { key = ["id"], log = false, renamed = { town = "city" } }\n'))
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "town", "member"]
    assert rows(erp.target, f"select * from {PEOPLE}") == rows(erp.source, "select * from people")


def test_renamed_left_in_the_definition_does_nothing_while_the_old_column_is_delivered_or_once_renamed(erp):
    people(erp, table='{ key = ["id"], renamed = { town = "city" } }')  # story 29
    view = "select 'raw_erp.people__history'::regclass::oid"
    for change in ["update people set name = 'p' where id = 1", "alter table people rename column city to town",
                   "update people set name = 'q' where id = 1"]:
        before = erp.target(view)
        erp.source(change)
        again(erp)
        if "rename" not in change:  # a table whose columns stay takes no lock and keeps its history view
            assert erp.target(view) == before
            assert erp.target(f"select count(*) from _rowvioli.columns__log {THIS_RUN}") == [(0,)]
    assert columns(erp, PEOPLE) == ["id", "name", "town", "member"]
    log_replays(erp, PEOPLE)


def test_renamed_left_in_the_definition_does_nothing_while_the_source_delivers_both_columns(erp):  # story 29
    people(erp, table='{ key = ["id"], renamed = { town = "city" } }')
    erp.source("alter table people add column town text; update people set town = upper(city)")
    again(erp)
    assert columns(erp, PEOPLE) == ["id", "name", "city", "member", "town"]
    assert erp.target(RECORD) == [("I", "town", None, "source", None)]
    assert rows(erp.target, f"select * from {PEOPLE}") == rows(erp.source, "select * from people")
    log_replays(erp, PEOPLE)


def test_renamed_across_two_families_stops_the_run_and_changes_nothing(erp):
    people(erp)
    erp.source("alter table people rename column member to active; alter table people alter active type text")
    apply(erp, definition(erp, '"public.people" = { key = ["id"], renamed = { active = "member" } }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).replace("***", "x") == ("column member is renamed active in the table's definition, but boolean and text are "
                           "types of two families, so their values are not the same: take active out of renamed")
    assert columns(erp, PEOPLE) == ["id", "name", "city", "member"]


@pytest.mark.parametrize("renamed", ["", ', renamed = { town = "city" }'])
def test_F2_a_renamed_header_of_a_file_is_a_new_column_unless_renamed_says_it_is_a_rename(files, renamed):
    csv = files.dir / "files" / "people.csv"
    csv.write_text("id;name;city\n1;Anna;Bonn\n2;Ben;Essen\n")
    table = '"people.csv" = {{ key = ["id"], sep = ";"{} }}\n'
    assert load_file(files, table.format(""))[0] == 0
    csv.write_text("id;name;town\n1;Anna;Bonn\n2;Ben;Essen\n")
    assert load_file(files, table.format(renamed))[0] == 0
    mirror = "select * from raw_files.people order by id"
    if renamed:
        assert columns(files, "raw_files.people") == ["id", "name", "town"]
        assert files.target(mirror) == [("1", "Anna", "Bonn"), ("2", "Ben", "Essen")]
        assert files.target("select count(*) from raw_files.people__log " + THIS_RUN) == [(0,)]
    else:  # nothing is proven without a catalog: the old column is empty from now on
        assert files.target(mirror) == [("1", "Anna", None, "Bonn"), ("2", "Ben", None, "Essen")]
    log_replays(files, "raw_files.people")


def test_renamed_to_a_name_the_change_log_has_stops_and_says_what_to_rename(erp):
    people(erp)
    erp.source("alter table people add column town text")
    again(erp)
    erp.source("alter table people drop column town")
    again(erp)
    erp.source("alter table people rename column city to town")
    apply(erp, definition(erp, '"public.people" = { key = ["id"], renamed = { town = "city" } }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).startswith("column city is renamed town in the table's definition, but the change log has a "
                                  "column town already: rename that column of the change log")
