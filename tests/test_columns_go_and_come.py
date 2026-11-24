"""A column goes and comes back: the mirror follows the source, the change log keeps what was (spec tests, stage 2;
the numbers are those of `.scratch/schema-changes/cases.md`)."""
import psycopg
import pytest

from test_checks import MIRROR, failed
from test_columns import LAST
from test_history import LOADED_AT, again
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)


def columns(rv, table="raw_erp.customers"):
    return [c for (c,) in rv.target("select attname from pg_attribute where attrelid = %s::regclass and attnum > 0 "
                                    "and not attisdropped order by attnum", [table])]


def log_replays(rv, table="raw_erp.customers"):
    """The invariant: the change log replayed, the latest version of each key without the D rows, gives the mirror."""
    key = ", ".join(f'"{k}"' for (k,) in rv.target(
        "select a.attname from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
        "where i.indrelid = %s::regclass and i.indisprimary", [table]))
    names = ", ".join(f'"{c}"' for c in columns(rv, table))
    replay = rows(rv.target, f"select {names} from (select distinct on ({key}) _op, {names} from {table}__log "
                             f"order by {key}, _loaded_at desc, _run desc) r where _op <> 'D'")
    assert replay == rows(rv.target, f"select {names} from {table}")


LOG = "select _op, customer_no, city from raw_erp.customers__log where _run = (select max(run) from _rowvioli.runs) " \
      "order by customer_no"
CITY = "select city, _valid_from, _valid_to from raw_erp.customers__history where customer_no = 1 order by _valid_from"


def test_A5_a_column_gone_from_the_source_leaves_the_mirror_and_its_values_stay_in_the_change_log(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    places = erp.target("select customer_no, ctid::text from raw_erp.customers order by 1")
    erp.source("alter table customers drop column city")
    second = again(erp)
    assert columns(erp) == ["customer_no", "name"]
    assert "city" in columns(erp, "raw_erp.customers__log")
    # one U for every row that had a value (Cleo had none), which ends the version that had it
    assert erp.target(LOG) == [("U", 1, None), ("U", 2, None)]
    assert erp.target(CITY) == [("Bonn", first, second), (None, second, None)]
    # story 5: the mirror's rows are not rewritten for it
    assert erp.target("select customer_no, ctid::text from raw_erp.customers order by 1") == places
    assert erp.target(LAST) == [("U", "city", False, "source", None)]
    log_replays(erp)


@pytest.mark.parametrize("table", ['{ key = ["customer_no"], log = false }', "{}"])
def test_A5_without_a_change_log_a_gone_column_stops_the_run_and_says_how_to_drop_it(erp, table):
    apply(erp, definition(erp, f'"public.customers" = {table}\n'))
    ok(erp)
    before = rows(erp.target, MIRROR)
    erp.source("alter table customers drop column city")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ("column city is missing in the source; without a change log its values are nowhere else, "
                           'so a person drops it: ALTER TABLE "raw_erp"."customers" DROP COLUMN "city"')
    assert rows(erp.target, MIRROR) == before


def test_a_column_a_person_added_to_the_mirror_is_never_dropped_and_stops_the_run(erp):  # story 8, cases G1
    ok(erp)
    erp.target("alter table raw_erp.customers add column memo text")
    erp.target("update raw_erp.customers set memo = 'mine'")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).startswith("column memo of the mirror is not in the change log, so it is not known to be "
                                  "from the source; drop it from the mirror")
    assert erp.target("select distinct memo from raw_erp.customers") == [("mine",)]


def test_a_table_stuck_on_a_column_missing_in_the_source_resolves_with_the_first_run(erp):  # story 45, cases E12
    ok(erp)
    erp.source("alter table customers drop column city")
    # as a run of the version before left it, failing for a while
    erp.target("update _rowvioli.tables set reason = 'column city is missing in the source', attempts = 3, "
               "requested_at = now()")
    ok(erp)
    assert erp.target("select status, attempts, reason from _rowvioli.status") == [("ok", 0, None)]
    assert columns(erp) == ["customer_no", "name"]
    log_replays(erp)


def test_A6_a_gone_column_a_consumers_view_reads_stops_the_run_naming_the_view_and_nothing_is_published(erp):
    ok(erp)
    erp.target("create schema reporting")
    erp.target("create view reporting.by_city as select city, count(*) from raw_erp.customers group by city")
    before = rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")
    erp.source("alter table customers drop column city")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.startswith("column city is gone from the source and would leave the mirror raw_erp.customers, but "
                             "view reporting.by_city depends on column city of table raw_erp.customers"), reason
    assert (rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")) == before
    assert erp.target("select count(*) from _rowvioli.columns__log where _op <> 'I'") == [(0,)]
    erp.target("drop view reporting.by_city")  # the way out
    again(erp)
    assert columns(erp) == ["customer_no", "name"]
    log_replays(erp)


def test_A7_A9_indexes_checks_and_column_grants_that_go_with_a_column_are_in_the_note(erp):
    ok(erp)
    role = "consumer_" + erp.target("select current_database()")[0][0]
    erp.target(f"create role {role}")
    try:
        erp.target("create index by_name_city on raw_erp.customers (name, city)")
        erp.target("alter table raw_erp.customers add constraint city_named check (city <> '')")
        erp.target(f"grant select (city) on raw_erp.customers to {role}")
        erp.target(f"grant select on raw_erp.customers to {role}")
        erp.source("alter table customers drop column city")
        again(erp)
        assert erp.target(LAST) == [("U", "city", False, "source",
                                     f"index raw_erp.by_name_city, constraint city_named on table raw_erp.customers, "
                                     f"the grant of SELECT to {role} went with it")]
        assert erp.target("select has_table_privilege(%s, 'raw_erp.customers', 'select')", [role]) == [(True,)]
        log_replays(erp)
    finally:
        erp.target(f"drop owned by {role}")
        erp.target(f"drop role {role}")


def test_A8_a_function_that_reads_a_gone_column_breaks_at_its_next_call_and_the_record_says_since_when(erp):
    ok(erp)
    erp.target("create function cities() returns bigint language plpgsql as "
               "$$ begin return (select count(city) from raw_erp.customers); end $$")
    erp.source("alter table customers drop column city")
    loaded_at = again(erp)
    with pytest.raises(psycopg.errors.UndefinedColumn):
        erp.target("select cities()")
    assert erp.target("select _loaded_at from _rowvioli.columns__log where \"column\" = 'city' and _op = 'U'") == [
        (loaded_at,)]


def test_A10_a_gone_key_column_stops_the_run_as_before(erp):
    ok(erp)
    erp.source("alter table customers drop column customer_no")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == "table public.customers has no column customer_no; it has: name, city"
    assert columns(erp) == ["customer_no", "name", "city"]
