"""The columns of every mirror, kept like rows: `_rowvioli.columns`, its log and its history (spec tests, stage 1)."""
import json

import psycopg
import pytest

from test_history import again
from test_run import apply, definition, erp, ok  # noqa: F401 (erp is a fixture)

COLUMNS = ('select "column", type, "key", mirror, "by" from _rowvioli.columns__history '
           "where target_table = %s and _valid_to is null order by 1")
LAST = ('select _op, "column", mirror, "by", note from _rowvioli.columns__log where _run = '
        '(select max(run) from _rowvioli.runs) order by "column"')
FIELDS = 'target_schema, target_table, "column", type, source_type, "key", mirror, was, "by", note, id'


def replays(rv):
    """The invariant: the columns log, replayed, gives the columns table."""
    replay = rv.target(f"""select {FIELDS} from (select distinct on (target_schema, target_table, "column") *
                             from _rowvioli.columns__log
                            order by target_schema, target_table, "column", _loaded_at desc) l where _op <> 'D'
                           order by 1, 2, 3""")
    assert replay == rv.target(f"select {FIELDS} from _rowvioli.columns order by 1, 2, 3")


def test_the_first_run_enters_every_column_of_a_table_with_or_without_a_key_as_found(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"] }\n"public.notes" = {}\n'))
    ok(erp)
    assert erp.target(COLUMNS, ["customers"]) == [("city", "text", None, True, "found"),
                                                  ("customer_no", "integer", 1, True, "found"),
                                                  ("name", "text", None, True, "found")]
    assert erp.target(COLUMNS, ["notes"]) == [("n", "integer", None, True, "found"),
                                              ("txt", "text", None, True, "found")]
    assert erp.target("select distinct id = (select id from _rowvioli.tables where target_table = 'notes') "
                      "from _rowvioli.columns where target_table = 'notes'") == [(True,)]
    replays(erp)


def test_a_new_source_column_gets_an_I_with_the_moment_of_the_rows_loaded_with_it(erp):
    ok(erp)
    erp.source("alter table customers add column phone text")
    erp.source("update customers set phone = '0228' where customer_no = 1")
    again(erp)
    assert erp.target(LAST) == [("I", "phone", True, "source", None)]
    assert erp.target("select source_type, type from _rowvioli.columns where \"column\" = 'phone'") == [("text", "text")]
    assert erp.target("select distinct _loaded_at from _rowvioli.columns__log where _run = (select max(run) "
                      "from _rowvioli.runs)") == erp.target("select distinct _loaded_at from raw_erp.customers__log "
                                                            "where _run = (select max(run) from _rowvioli.runs)")
    again(erp)  # nothing changed: nothing recorded
    assert erp.target(LAST) == []
    replays(erp)


def test_the_columns_history_gives_the_columns_a_table_had_at_a_moment(erp):
    ok(erp)
    first = erp.target("select loaded_at from _rowvioli.tables")[0][0]
    erp.source("alter table customers add column phone text")
    second = again(erp)
    at = ('select "column" from _rowvioli.columns__history where target_table = \'customers\' and mirror '
          "and _valid_from <= %s and (_valid_to > %s or _valid_to is null) order by 1")
    assert erp.target(at, [first, first]) == [("city",), ("customer_no",), ("name",)]
    assert erp.target(at, [second, second]) == [("city",), ("customer_no",), ("name",), ("phone",)]


def test_a_column_dropped_from_the_mirror_by_hand_and_added_again_by_the_run_is_recorded_as_hand(erp):
    ok(erp)
    erp.target("alter table raw_erp.customers drop column city")
    again(erp)
    assert erp.target(LAST) == [("U", "city", True, "hand", None)]
    replays(erp)


def test_a_column_dropped_from_the_change_log_by_hand_and_added_again_by_the_run_is_recorded_as_hand(erp):
    ok(erp)
    erp.target("alter table raw_erp.customers__log drop column city cascade")  # the history view goes with it
    again(erp)
    assert erp.target(LAST) == [("U", "city", True, "hand", None)]
    replays(erp)


def test_a_type_widened_by_hand_in_the_mirror_is_followed_in_the_change_log_and_recorded_as_hand(erp):
    erp.source("create table prices (id int primary key, amount numeric(10,2))")
    erp.source("insert into prices values (1, 1.50)")
    apply(erp, definition(erp, '"public.prices" = { key = ["id"] }\n'))
    ok(erp)
    erp.target("alter table raw_erp.prices alter column amount type numeric(12,2)")
    again(erp)
    assert erp.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'amount' "
                      "and attrelid in ('raw_erp.prices'::regclass, 'raw_erp.prices__log'::regclass)") == [
        ("numeric(12,2)",), ("numeric(12,2)",)]
    assert erp.target("select type, source_type, \"by\" from _rowvioli.columns where \"column\" = 'amount'") == [
        ("numeric(12,2)", "numeric(10,2)", "hand")]
    replays(erp)


def test_a_column_a_person_added_to_the_change_log_is_recorded_as_hand_and_not_in_the_mirror(erp):
    ok(erp)
    erp.target("alter table raw_erp.customers__log add column memo text")
    again(erp)
    assert erp.target(LAST) == [("I", "memo", False, "hand", None)]
    replays(erp)


def test_a_mirror_renamed_by_hand_appears_under_its_new_name_and_the_old_name_is_closed(erp):
    ok(erp)
    for old, new in [("customers", "clients"), ("customers__log", "clients__log")]:
        erp.target(f"alter table raw_erp.{old} rename to {new}")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], target_table = "clients" }\n'))
    again(erp)
    assert erp.target(COLUMNS, ["clients"]) == [("city", "text", None, True, "found"),
                                                ("customer_no", "integer", 1, True, "found"),
                                                ("name", "text", None, True, "found")]
    assert erp.target("select distinct _op, \"by\" from _rowvioli.columns__log where target_table = 'customers' "
                      "and _run = (select max(run) from _rowvioli.runs)") == [("D", "hand")]
    assert erp.target("select count(*) from _rowvioli.columns where target_table = 'customers'") == [(0,)]
    replays(erp)


def test_a_name_left_behind_by_one_table_and_taken_by_another_is_recorded_once_under_the_other(erp):
    erp.source("create table clients (customer_no int primary key, name text, city text)")
    erp.source("insert into clients select * from customers")
    ok(erp)  # customers into raw_erp.customers; then customers moves on and clients takes the table it left
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], target_table = "moved" }\n'
                               '"public.clients" = { key = ["customer_no"], target_table = "customers" }\n'))
    for _ in range(2):  # the second run of clients changes nothing, so it records nothing
        erp.target("update _rowvioli.tables set requested_at = now()")
        ok(erp, "erp", "public.clients")
    assert erp.target(LAST) == []
    assert erp.target("select distinct c.id = t.id from _rowvioli.columns c join _rowvioli.tables t "
                      "on t.source_table = 'public.clients' where c.target_table = 'customers'") == [(True,)]
    replays(erp)


@pytest.mark.parametrize("before, was", [("'0.0.1', '9'", "program 0.0.1 to {}, driver 9 to none"),
                                         ("null, null", "program none to {}, driver none to none")])
def test_another_program_or_driver_version_or_none_marks_what_the_source_changed_as_reader_with_both(erp, before, was):
    ok(erp)
    erp.target(f"update _rowvioli.runs set (program_version, driver_version) = ({before})")
    erp.source("alter table customers add column phone text")
    again(erp)
    version = erp.run("--version").stdout.split()[-1]
    assert erp.target(LAST) == [("I", "phone", True, "reader", was.format(version))]


def listen(rv):
    c = psycopg.connect(rv.target_url, autocommit=True)
    c.execute("listen rowvioli_schema")
    return c


def heard(c):
    return [json.loads(n.payload) for n in c.notifies(timeout=1, stop_after=1)]


def test_a_run_that_changes_columns_notifies_on_commit_and_one_that_fails_does_not(erp):
    ok(erp)
    listener = listen(erp)
    erp.source("alter table customers add column phone text")
    again(erp)
    [(run,)] = erp.target("select max(run) from _rowvioli.runs")
    assert heard(listener) == [{"schema": "raw_erp", "table": "customers", "run": run}]
    erp.source("alter table customers add column fax text")
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    # a consumer's check that Postgres runs at COMMIT, after the run has recorded fax and notified
    erp.target("create function no_koeln() returns trigger language plpgsql as "
               "$$ begin if new.city = 'Köln' then raise exception 'no Köln'; end if; return null; end $$")
    erp.target("create constraint trigger no_koeln after insert on raw_erp.customers deferrable initially deferred "
               "for each row execute function no_koeln()")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert erp.run("run").returncode == 1
    assert "no Köln" in erp.target("select reason from _rowvioli.tables")[0][0]
    assert heard(listener) == []
    assert erp.target("select count(*) from _rowvioli.columns where \"column\" = 'fax'") == [(0,)]
    listener.close()


def test_the_first_fill_notifies_nobody(erp):
    listener = listen(erp)
    ok(erp)
    assert heard(listener) == []
    listener.close()


def test_one_right_on_the_history_view_is_all_an_auditor_needs(erp):
    ok(erp)
    erp.target("create role auditor login password 'a'")
    try:
        erp.target("grant usage on schema _rowvioli to auditor")
        erp.target("grant select on _rowvioli.columns__history to auditor")
        url = erp.target_url.replace("postgres:x", "auditor:a")
        with psycopg.connect(url) as c:
            assert c.execute("select count(*) from _rowvioli.columns__history").fetchone()[0] == 3
    finally:
        erp.target("drop owned by auditor")
        erp.target("drop role auditor")
