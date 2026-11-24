"""A column goes and comes back: the mirror follows the source, the change log keeps what was (spec tests, stage 2;
the numbers are those of `.scratch/schema-changes/cases.md`)."""
import json
import time

import psycopg
import pytest

from conftest import until
from test_checks import MIRROR, failed
from test_columns import LAST, heard, listen
from test_history import LOADED_AT, again
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)


def columns(rv, table="raw_erp.customers"):
    return [c for (c,) in rv.target("select attname from pg_attribute where attrelid = %s::regclass and attnum > 0 "
                                    "and not attisdropped order by attnum", [table])]


def log_replays(rv, table="raw_erp.customers"):
    """The invariant: the change log replayed from the last change of key, the latest version of each key without the
    D rows, gives the mirror. The comment on _op says when the key changed last."""
    key = ", ".join(f'"{k}"' for (k,) in rv.target(
        "select a.attname from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
        "where i.indrelid = %s::regclass and i.indisprimary", [table]))
    names = ", ".join(f'"{c}"' for c in columns(rv, table))
    [(keys,)] = rv.target("select col_description(%s::regclass, (select attnum from pg_attribute where attrelid = "
                          "%s::regclass and attname = '_op'))", [f"{table}__log"] * 2)
    since = json.loads(keys)[-1].get("from") if keys else None
    stretch = "_loaded_at > %s or _loaded_at = %s and _op = 'I'" if since else "true"
    replay = rows(lambda q: rv.target(q, [since, since] if since else None),
                  f"select {names} from (select distinct on ({key}) _op, {names} from {table}__log where {stretch} "
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


def test_a_column_goes_in_the_run_that_changes_deletes_and_inserts_rows(erp):  # story 4
    ok(erp)
    erp.source("alter table customers drop column city")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.source("delete from customers where customer_no = 2")
    erp.source("insert into customers values (4, 'Dora')")
    again(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    assert erp.target(LOG) == [("U", 1, None), ("D", 2, "Essen"), ("I", 4, None)]
    log_replays(erp)


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
    listener = listen(erp)
    reason = failed(erp)
    assert reason.startswith("column city is gone from the source and would leave the mirror raw_erp.customers, but "
                             "view reporting.by_city depends on column city of table raw_erp.customers"), reason
    assert (rows(erp.target, MIRROR), erp.target("select count(*) from raw_erp.customers__log")) == before
    assert erp.target("select count(*) from _rowvioli.columns__log where _op <> 'I'") == [(0,)]
    assert heard(listener) == []
    listener.close()
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
    log_replays(erp)


def test_A10_a_gone_key_column_stops_the_run_as_before(erp):
    ok(erp)
    erp.source("alter table customers drop column customer_no")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == "table public.customers has no column customer_no; it has: name, city"
    assert columns(erp) == ["customer_no", "name", "city"]


def test_A11_A15_a_column_back_with_its_type_continues_its_log_column_and_the_record_shows_the_gap(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    attnum = "select attnum from pg_attribute where attrelid = 'raw_erp.customers__log'::regclass and attname = 'city'"
    before = erp.target(attnum)
    erp.source("alter table customers drop column city")
    second = again(erp)
    erp.source("alter table customers add column city text")
    erp.source("update customers set city = 'Bonn' where customer_no = 1")
    third = again(erp)
    assert columns(erp) == ["customer_no", "name", "city"]
    assert erp.target(attnum) == before
    assert erp.target(LOG) == [("U", 1, "Bonn")]
    assert erp.target(CITY) == [("Bonn", first, second), (None, second, third), ("Bonn", third, None)]
    # A15: nothing tells another meaning under the same name and type; the gap in the record is the only sign
    assert erp.target("select mirror, _valid_from from _rowvioli.columns__history where \"column\" = 'city' "
                      "order by _valid_from") == [(True, first), (False, second), (True, third)]
    log_replays(erp)


def test_A16_a_column_dropped_and_added_again_between_two_runs_is_a_U_for_each_row_whose_value_differs(erp):
    ok(erp)
    erp.source("alter table customers drop column city")
    erp.source("alter table customers add column city text")
    erp.source("update customers set city = 'Bonn' where customer_no = 1")
    again(erp)
    assert erp.target(LOG) == [("U", 2, None)]
    assert erp.target(LAST) == []
    log_replays(erp)


def test_A13_a_column_back_in_another_family_begins_anew_and_the_log_keeps_the_old_values_under_its_run(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    erp.source("alter table customers drop column city")
    again(erp)
    erp.source("alter table customers add column city integer")
    erp.source("update customers set city = 53111 where customer_no = 1")
    third = again(erp)
    [(run,)] = erp.target("select max(run) from _rowvioli.runs")
    assert columns(erp, "raw_erp.customers__log")[-2:] == [f"city__{run}", "city"]
    assert erp.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'city' "
                      "and attrelid in ('raw_erp.customers'::regclass, 'raw_erp.customers__log'::regclass)") == [
        ("integer",), ("integer",)]
    assert erp.target(f"select city__{run}, city, _valid_from from raw_erp.customers__history where customer_no = 1 "
                      "order by _valid_from")[::2] == [("Bonn", None, first), (None, 53111, third)]
    assert erp.target('select _op, "column", type, mirror, was from _rowvioli.columns__log where _run = %s '
                      'order by "column"', [run]) == [("U", "city", "integer", True, None),
                                                      ("I", f"city__{run}", "text", False, "city")]
    log_replays(erp)


def test_A14_text_then_integer_then_text_retires_two_log_columns_and_the_third_does_not_continue_the_first(erp):
    ok(erp)
    for type in ["integer", "text"]:
        erp.source("alter table customers drop column city")
        again(erp)
        erp.source(f"alter table customers add column city {type}")
        erp.source("update customers set city = 1 where customer_no = 1")
        again(erp)
    retired = [c for c in columns(erp, "raw_erp.customers__log") if c.startswith("city__")]
    assert len(retired) == 2
    assert erp.target(f"select count({retired[0]}), count({retired[1]}), count(city) "
                      "from raw_erp.customers__log") == [(2, 1, 1)]
    log_replays(erp)


def test_A12_a_column_back_in_a_wider_type_of_its_family_keeps_the_logs_type_while_the_values_fit(erp):
    erp.source("create table prices (id int primary key, amount integer)")
    erp.source("insert into prices values (1, 10), (2, null)")
    apply(erp, definition(erp, '"public.prices" = { key = ["id"] }\n'))
    ok(erp)
    erp.source("alter table prices drop column amount")
    again(erp)
    erp.source("alter table prices add column amount bigint")
    erp.source("update prices set amount = 20 where id = 1")
    again(erp)
    assert erp.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'amount' "
                      "and attrelid in ('raw_erp.prices'::regclass, 'raw_erp.prices__log'::regclass)") == [
        ("integer",), ("integer",)]
    assert columns(erp, "raw_erp.prices__log") == ["_run", "_op", "_loaded_at", "id", "amount"]
    assert erp.target("select type, source_type, mirror from _rowvioli.columns where \"column\" = 'amount'") == [
        ("integer", "bigint", True)]
    assert erp.target("select amount from raw_erp.prices order by id") == [(20,), (None,)]
    log_replays(erp, "raw_erp.prices")


@pytest.mark.parametrize("type, value", [("timestamp", "2024-01-01 12:30"), ("numeric", "1.5")])
def test_A12_a_column_back_in_its_family_with_a_value_the_logs_type_would_change_stops_and_changes_nothing(
        erp, type, value):
    erp.source("create table events (id int primary key, day date, n integer)")
    erp.source("insert into events values (1, '2024-01-01', 1)")
    apply(erp, definition(erp, '"public.events" = { key = ["id"] }\n'))
    ok(erp)
    column = "day" if type == "timestamp" else "n"
    erp.source(f"alter table events drop column {column}")
    again(erp)
    erp.source(f"alter table events add column {column} {type}")
    erp.source(f"update events set {column} = '{value}'")
    erp.target("update _rowvioli.tables set requested_at = now()")
    # never is a value cut to the change log's type (decision 5 will widen it instead)
    assert failed(erp).startswith(f"column {column} holds a value that its type ")
    assert columns(erp, "raw_erp.events") == ["id", "n" if column == "day" else "day"]


@pytest.mark.parametrize("earlier", [True, False])
def test_a_retired_name_the_source_takes_stops_and_says_what_to_rename(erp, earlier):  # story 10
    ok(erp)
    erp.source("alter table customers drop column city")
    again(erp)
    [(run,)] = erp.target("select max(run) + 1 + %s::int from _rowvioli.runs", [earlier])  # the run that retires
    erp.source(f"alter table customers add column city__{run} text")
    erp.source(f"update customers set city__{run} = 'new'")
    if earlier:  # a source column that took the name a run before
        again(erp)
    erp.source("alter table customers add column city integer")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert erp.target("select max(run) from _rowvioli.runs") == [(run,)]
    assert reason.startswith(f"column city of the change log is to keep its old values under city__{run}, a name "
                             "that is taken: rename that column of the change log"), reason
    assert erp.target("select count(*) from raw_erp.customers__log where city = 'Bonn'") == [(1,)]
    log_replays(erp)


def test_A19_a_new_source_column_named_like_a_retired_one_stops_until_a_person_renames_the_log_column(erp):
    ok(erp)
    erp.source("alter table customers drop column city")
    again(erp)
    erp.source("alter table customers add column city integer")
    again(erp)
    [(run,)] = erp.target("select max(run) from _rowvioli.runs")
    erp.source(f"alter table customers add column city__{run} text")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.startswith(f"column city__{run} of the source has the name under which the change log keeps the "
                             "old values of city: rename that column of the change log"), reason
    erp.target(f"alter table raw_erp.customers__log rename column city__{run} to city_text")  # the way out
    erp.target("drop view raw_erp.customers__history")
    again(erp)
    assert columns(erp) == ["customer_no", "name", "city", f"city__{run}"]
    log_replays(erp)


def test_a_retired_name_longer_than_postgres_takes_stops_and_says_what_to_rename(erp):  # story 10
    long = "y" * 62  # not x: the source's password is x, and the reason hides it
    erp.source(f"alter table customers add column {long} text")
    ok(erp)
    erp.source(f"alter table customers drop column {long}")
    again(erp)
    erp.source(f"alter table customers add column {long} integer")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.startswith(f"column {long} of the change log is to keep its old values under {long}__"), reason
    assert "a name that is longer than 63 bytes: rename that column of the change log" in reason
    erp.target(f"alter table raw_erp.customers__log rename column {long} to y_text")
    erp.target("drop view raw_erp.customers__history")
    again(erp)
    log_replays(erp)


def test_A23_a_column_that_finds_postgres_1600_used_up_by_dropped_ones_stops_and_names_the_way_out(erp):
    ok(erp)
    erp.target("do $$ begin for i in 1..1597 loop alter table raw_erp.customers add column c int; "
               "alter table raw_erp.customers drop column c; end loop; end $$")
    erp.source("alter table customers add column phone text")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ('column phone cannot be added to "raw_erp"."customers": Postgres counts the columns once '
                           "dropped from a table towards its 1600; rewrite the table to free them, by dump and "
                           "restore")


def test_a_run_never_waits_for_a_lock_while_holding_one_and_gives_up_after_10s(erp):  # stories 43, 44
    ok(erp)
    erp.source("alter table customers drop column city")
    erp.target("update _rowvioli.tables set requested_at = now()")
    with psycopg.connect(erp.target_url) as consumer:  # a consumer joining history and mirror, history first
        consumer.execute("select * from raw_erp.customers__history")
        started = time.monotonic()
        assert failed(erp).startswith("raw_erp.customers, its change log or its history view stayed in use for 10 s, "
                                      "so its columns could not change")
        assert time.monotonic() - started >= 10
        consumer.rollback()
        erp.target("update _rowvioli.tables set requested_at = now()")
        consumer.execute("select * from raw_erp.customers__history")
        p = erp.start("run")
        until(lambda: erp.target("select 1 from _rowvioli.runs where status = 'running'"))
        time.sleep(1)  # the run tries its lock meanwhile
        consumer.execute("set local lock_timeout = '2s'")
        consumer.execute("select * from raw_erp.customers")  # the run holds nothing it would wait on
        consumer.commit()
    assert p.wait(timeout=30) == 0, p.stdout.read()
    assert columns(erp) == ["customer_no", "name"]
    log_replays(erp)
