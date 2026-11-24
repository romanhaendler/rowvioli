"""A rename: proven by the data or stated in the definition, renamed in mirror and change log with no row written
(spec tests, stage 5; the numbers are those of `.scratch/schema-changes/cases.md`)."""
import pytest

from test_checks import failed
from test_columns_go_and_come import columns, log_replays
from test_history import again
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
])
def test_a_rename_is_not_assumed_where_the_data_do_not_prove_it(erp, n, steps, old, new):  # story 27
    people(erp, n)
    for step in steps:
        erp.source(step)
        again(erp)
    gone_and_come(erp, old, new)


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
