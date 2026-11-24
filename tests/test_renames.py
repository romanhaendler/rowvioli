"""A rename: proven by the data or stated in the definition, renamed in mirror and change log with no row written
(spec tests, stage 5; the numbers are those of `.scratch/schema-changes/cases.md`)."""
from test_columns_go_and_come import columns, log_replays
from test_history import again
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)

PEOPLE = "raw_erp.people"
THIS_RUN = "where _run = (select max(run) from _rowvioli.runs)"
RECORD = f'select _op, "column", was, "by", note from _rowvioli.columns__log {THIS_RUN} order by "column"'


def people(rv, n=30, table='{ key = ["id"] }'):
    """A table of n people in six cities, loaded once."""
    rv.source("create table people (id int primary key, name text, city text)")
    rv.source("insert into people select i, 'p' || i, (array['Bonn', 'Essen', 'Ulm', 'Kiel', 'Jena', 'Hof'])[i %% 6 + 1] "
              "from generate_series(1, %s) i", [n])
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
    assert columns(erp, PEOPLE) == ["id", "name", "town"]
    assert columns(erp, f"{PEOPLE}__log")[-1] == "town"
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
