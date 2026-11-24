"""A change log that exists is complete, and it says when; its history view (spec tests 10 to 20)."""
import psycopg
import pytest

from test_checks import failed
from test_run import apply, definition, erp, ok, rows, run  # noqa: F401 (erp is a fixture)

HISTORY = "select customer_no, city, _valid_from, _valid_to from raw_erp.customers__history"
MIRROR = "select customer_no, name, city from raw_erp.customers"
ORDER = " order by customer_no, _valid_from"
LOADED_AT = "select loaded_at from _rowvioli.tables"


def again(rv):
    rv.target("update _rowvioli.tables set requested_at = now()")
    ok(rv)
    return rv.target(LOADED_AT)[0][0]


def test_the_history_view_gives_every_version_with_the_time_it_was_valid(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.source("delete from customers where customer_no = 2")
    second = again(erp)
    assert first < second
    assert erp.target(HISTORY + ORDER) == [
        (1, "Bonn", first, second), (1, "Köln", second, None), (2, "Essen", first, second), (3, None, first, None)]
    assert erp.target("select distinct _loaded_at from raw_erp.customers__log where _run = "
                      "(select max(run) from _rowvioli.runs)") == [(second,)]


def at(rv, moment):
    """The table as it was at a moment: the one condition of docs/target.md "History"."""
    return rows(lambda q: rv.target(q, [moment, moment]), "select customer_no, name, city from "
                "raw_erp.customers__history where _valid_from <= %s and (_valid_to > %s or _valid_to is null)")


def test_the_condition_for_a_moment_gives_the_mirror_as_it_was_then(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    then = rows(erp.target, MIRROR)
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.source("delete from customers where customer_no = 2")
    erp.source("insert into customers values (4, 'Dora', 'Bonn')")
    second = again(erp)
    assert at(erp, first + (second - first) / 2) == then
    assert at(erp, second) == rows(erp.target, MIRROR) != then


def test_a_row_deleted_and_back_shows_two_periods_with_a_gap(erp):
    ok(erp)
    first = erp.target(LOADED_AT)[0][0]
    erp.source("delete from customers where customer_no = 2")
    second = again(erp)
    erp.source("insert into customers values (2, 'Ben', 'Essen')")
    third = again(erp)
    assert erp.target(HISTORY + " where customer_no = 2" + ORDER) == [(2, "Essen", first, second),
                                                                       (2, "Essen", third, None)]


def test_a_new_source_column_appears_in_the_view_empty_in_the_older_versions(erp):
    ok(erp)
    erp.source("alter table customers add column phone text")
    erp.source("update customers set phone = '0228' where customer_no = 1")
    again(erp)
    assert erp.target("select customer_no, phone, _valid_to is null from raw_erp.customers__history"
                      " where customer_no = 1 order by _valid_from") == [(1, None, False), (1, "0228", True)]


def test_a_dropped_history_view_is_there_again_after_the_next_run(erp):
    ok(erp)
    erp.target("drop view raw_erp.customers__history")
    again(erp)
    assert at(erp, erp.target(LOADED_AT)[0][0]) == rows(erp.target, MIRROR)


def test_a_table_without_a_key_or_with_log_false_has_no_change_log_and_no_history_view(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], log = false }\n"public.notes" = {}\n'))
    ok(erp)
    assert erp.target("select to_regclass(n) from unnest(array['raw_erp.customers__log', 'raw_erp.customers__history',"
                      " 'raw_erp.notes__log', 'raw_erp.notes__history']) n") == [(None,)] * 4


def test_the_view_is_read_by_a_role_with_rights_on_the_tables_schema_and_none_on_rowvioli(erp):
    ok(erp)
    with psycopg.connect(erp.target_url, autocommit=True) as c:
        role = "reader_" + c.execute("select current_database()").fetchone()[0]
        c.execute(f"create role {role}")
        c.execute(f"grant usage on schema raw_erp to {role}")
        c.execute(f"grant select on all tables in schema raw_erp to {role}")
        c.execute(f"set role {role}")
        assert c.execute("select count(*) from raw_erp.customers__history").fetchone() == (3,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select * from _rowvioli.runs")


GRANTS = """select a.privilege_type, case a.grantee when 0 then 'public' else a.grantee::regrole::text end,
                  a.is_grantable, null::name from pg_class r, aclexplode(r.relacl) a
             where r.oid = 'raw_erp.customers__history'::regclass and a.grantee <> r.relowner
            union all
            select a.privilege_type, case a.grantee when 0 then 'public' else a.grantee::regrole::text end,
                   a.is_grantable, c.attname from pg_attribute c, aclexplode(c.attacl) a
             where c.attrelid = 'raw_erp.customers__history'::regclass order by 4 nulls first, 2"""


def test_a_history_view_built_anew_keeps_the_grants_given_on_it_by_name(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], renamed = { town = "city" } }\n'))
    ok(erp)
    role = "reader_" + erp.target("select current_database()")[0][0]
    erp.target(f"create role {role}")
    try:
        erp.target(f"grant usage on schema raw_erp to {role}")
        erp.target(f"grant select on raw_erp.customers__history to {role} with grant option")
        erp.target("grant select (city) on raw_erp.customers__history to public")
        for change in ["alter table customers rename column city to town", "alter table customers drop column name",
                       '"public.customers" = { key = ["customer_no", "town"] }\n']:
            if change.startswith("alter"):
                erp.source(change)
            else:
                erp.source("update customers set town = 'Ulm' where town is null")  # a key column holds no null
                apply(erp, definition(erp, change))
            again(erp)
            # the column granted follows its rename
            assert erp.target(GRANTS) == [("SELECT", role, True, None), ("SELECT", "public", False, "town")], change
            with psycopg.connect(erp.target_url, autocommit=True) as c:
                c.execute(f"set role {role}")
                assert c.execute("select count(*) from raw_erp.customers__history").fetchone() == \
                    erp.target("select count(*) from raw_erp.customers__history")[0], change
    finally:
        erp.target(f"drop owned by {role}")
        erp.target(f"drop role {role}")


WORKER = """GRANT USAGE ON SCHEMA _rowvioli TO {0};
GRANT SELECT ON _rowvioli.sources, _rowvioli.tables, _rowvioli.meta, _rowvioli.status TO {0};
GRANT UPDATE ON _rowvioli.tables TO {0};
GRANT SELECT, INSERT, UPDATE ON _rowvioli.runs TO {0};
GRANT USAGE ON ALL SEQUENCES IN SCHEMA _rowvioli TO {0};
GRANT SELECT, INSERT, UPDATE, DELETE ON _rowvioli.columns TO {0};
GRANT SELECT, INSERT ON _rowvioli.columns__log TO {0};
GRANT CREATE ON DATABASE {1} TO {0}"""  # docs/operation.md "The target"


@pytest.mark.parametrize("runs_as", ["a superuser", "a member of the grantor", "a worker's role alone",
                                     "a member of a grantor without its schema"])
def test_a_grant_passed_on_with_the_grant_option_comes_back_from_its_grantor_where_the_runs_role_may_act_as_it(
        erp, runs_as):
    db = erp.target("select current_database()")[0][0]
    worker, lender, borrower = (f"{name}_{db}" for name in ("worker", "lender", "borrower"))
    env = {}
    try:
        erp.target(f"create role {lender}; create role {borrower}")
        if runs_as != "a superuser":  # roles belong to the cluster: each its own name
            erp.target(f"create role {worker} login password 'w'")
            for statement in WORKER.format(worker, db).split(";\n"):
                erp.target(statement)
            env = {"ROWVIOLI_TARGET_URL": erp.target_url.replace("postgres:x@", f"{worker}:w@")}
        if runs_as.startswith("a member of"):
            erp.target(f"grant {lender} to {worker}")
        assert erp.run("run", env=env).returncode == 0
        erp.target(f"grant usage on schema raw_erp to {lender}, {borrower}")
        erp.target(f"grant select on raw_erp.customers__history to {lender} with grant option")
        with psycopg.connect(erp.target_url, autocommit=True) as c:
            c.execute(f"set role {lender}")
            c.execute(f"grant select on raw_erp.customers__history to {borrower}")
            c.execute(f"grant select (city) on raw_erp.customers__history to {borrower}")
        if runs_as == "a member of a grantor without its schema":  # it could not give the grant any more
            erp.target(f"revoke usage on schema raw_erp from {lender}")
        erp.source("alter table customers drop column name")  # the history view is built anew
        erp.target("update _rowvioli.tables set requested_at = now()")
        assert erp.run("run", env=env).returncode == 0
        grantors = """select a.grantee::regrole::text, a.grantor::regrole::text, c.attname from pg_class r
                        cross join lateral (select null::name attname, relacl acl union all select attname, attacl
                                              from pg_attribute where attrelid = r.oid and attacl is not null) c,
                        aclexplode(c.acl) a where r.oid = 'raw_erp.customers__history'::regclass
                        and a.grantee = %s::regrole"""
        # where the run's role may not act as the grantor, it gives the grant itself, as decision 54 says
        by = lender if runs_as in ("a superuser", "a member of the grantor") else worker
        assert sorted(erp.target(grantors, [borrower]), key=repr) == [(borrower, by, "city"), (borrower, by, None)]
        erp.target(f"revoke select on raw_erp.customers__history from {lender} cascade")  # takes the table's grant
        assert [g for g in erp.target(grantors, [borrower]) if not g[2]] == ([] if by == lender else
                                                                             [(borrower, by, None)])
    finally:
        erp.target("drop view if exists raw_erp.customers__history")  # with the grants on it, whoever gave them
        for role in (borrower, lender, worker):
            if erp.target("select 1 from pg_roles where rolname = %s", [role]):
                erp.target(f"drop owned by {role} cascade; drop role {role}")


LOG_FALSE = '"public.customers" = { key = ["customer_no"], log = false }\n'


def test_a_log_switched_on_later_begins_with_the_whole_mirror(erp):
    apply(erp, definition(erp, LOG_FALSE))
    ok(erp)
    apply(erp, definition(erp))
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    code, answer = run(erp)
    assert answer["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 0, "updated": 1, "deleted": 0}
    assert at(erp, erp.target(LOADED_AT)[0][0]) == rows(erp.target, MIRROR)
    assert erp.target("select _op, count(*) from raw_erp.customers__log group by 1") == [("I", 3)]


def test_a_log_switched_off_fails_the_next_run_until_log_and_view_are_dropped(erp):
    ok(erp)
    apply(erp, definition(erp, LOG_FALSE))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert "raw_erp.customers__log" in reason and "drop" in reason
    erp.target("drop table raw_erp.customers__log cascade")
    again(erp)


def test_a_mirror_dropped_without_its_log_fails_the_next_run_until_the_log_is_dropped(erp):
    ok(erp)
    erp.target("drop table raw_erp.customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert "raw_erp.customers__log" in reason and "drop" in reason
    assert erp.target("select to_regclass('raw_erp.customers')") == [(None,)]
    erp.target("drop table raw_erp.customers__log cascade")
    loaded_at = again(erp)
    assert erp.target("select distinct _valid_from from raw_erp.customers__history") == [(loaded_at,)]


@pytest.mark.parametrize("name", ["_loaded_at", "_valid_from", "_valid_to"])
def test_a_source_column_with_a_name_of_the_log_or_the_view_fails_the_run(erp, name):
    erp.source(f"alter table customers add column {name} text")
    reason = failed(erp)
    assert f"column {name} is a name of the change log or the history view" in reason
    assert "log = false frees it" in reason


def test_C2_a_key_taken_away_fails_naming_the_log_until_log_view_and_mirror_are_dropped(erp):
    ok(erp)
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert "no key any more" in reason and "raw_erp.customers__log" in reason and "DROP TABLE" in reason
    erp.target("drop table raw_erp.customers__log cascade")
    erp.target("drop table raw_erp.customers")
    again(erp)


@pytest.mark.parametrize("name", ["_op", "_run", "_loaded_at"])
@pytest.mark.parametrize("how", ["renamed", "another family"])
def test_a_name_of_the_change_log_the_source_brings_is_never_answered_by_renaming_the_change_logs_column(erp, name, how):
    ok(erp)
    if how == "renamed":  # as a program that did not refuse it applied it
        erp.target(f"""update _rowvioli.tables set options = '{{"renamed": {{"{name}": "city"}}}}'""")
        erp.source(f"alter table customers rename column city to {name}")
    else:
        erp.source(f"alter table customers add column {name} {'integer' if name == '_op' else 'text'}")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert f"column {name} is a name of the change log or the history view" in reason, reason
    assert "RENAME" not in reason


def test_the_name_op_is_said_not_to_be_free_to_take(erp):
    erp.source("alter table customers add column _op text")
    assert failed(erp) == ("column _op is a name of the change log or the history view, so a table with a key cannot "
                           "have it; _op cannot be freed: read the source through a view of it that names that column "
                           "otherwise")
