"""A real pg_dump of the target (docs/operation.md "The target"): beside a run that changes columns, and a dump taken
after every kind of change restored into an empty database, where a run goes on as before (ticket 14 of schema
changes)."""
import subprocess
import uuid

from conftest import _query, _url, until
from test_checks import failed
from test_columns import replays
from test_columns_go_and_come import columns, log_replays
from test_history import again
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)


def database(rv):
    return rv.target_url.rsplit("/", 1)[1]


def test_a_run_that_changes_columns_while_pg_dump_reads_the_target_gives_up_after_10s_and_the_next_one_goes_on(
        erp, servers):
    erp.source("insert into customers select g, 'n' || g, repeat('c', 50) from generate_series(4, 20000) g")
    ok(erp)
    # pg_dump holds its locks until it has written everything, and a pipe nobody reads until the test lets it keeps
    # it from finishing
    go = f"/tmp/go-{database(erp)}"
    dump = subprocess.Popen(["docker", "exec", servers["target"], "sh", "-c",
                             f"pg_dump -U postgres {database(erp)} | (until [ -e {go} ]; do sleep 0.2; done; wc -c)"],
                            stdout=subprocess.PIPE, text=True)
    until(lambda: erp.target("select 1 from pg_locks l join pg_stat_activity a using (pid) where a.application_name "
                             "= 'pg_dump' and l.relation = 'raw_erp.customers'::regclass"))
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    again(erp)  # rows alone: pg_dump's share lock lets them through
    erp.source("alter table customers drop column city")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).replace("***", "x") == (  # the source's password is x
        "raw_erp.customers, its change log or its history view stayed in use for 10 s, so its columns could not "
        "change; the next run tries again")
    subprocess.run(["docker", "exec", servers["target"], "touch", go], check=True)
    assert int(dump.communicate(timeout=30)[0]) > 1_000_000 and dump.returncode == 0
    subprocess.run(["docker", "exec", servers["target"], "rm", go], check=True)
    again(erp)
    assert columns(erp) == ["customer_no", "name"]
    log_replays(erp)


def test_a_dump_taken_after_every_kind_of_change_restores_and_a_run_against_it_goes_on(erp, servers):
    erp.source("insert into customers select g, 'n' || g, 'c' || (g % 7) from generate_series(4, 30) g;"
               "alter table customers add column amount int; update customers set amount = customer_no")
    ok(erp)
    role = f"consumer_{database(erp)}"
    erp.target(f"create role {role}")
    erp.target(f"grant select on raw_erp.customers__history to {role}")
    for change in ["alter table customers drop column city",  # gone
                   "alter table customers alter amount type bigint; update customers set amount = 1e12 where "
                   "customer_no = 1",  # widened
                   "alter table customers alter amount type text using amount || 'x'",  # another family
                   "alter table customers rename name to label"]:  # renamed, proven by 30 rows
        erp.source(change)
        again(erp)
    erp.source("alter table customers add column tenant int not null default 1")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "tenant"] }\n'))  # another key
    again(erp)
    restored, original = f"r_{uuid.uuid4().hex[:12]}", erp.target_url
    target = servers["target"]
    try:
        _query(_url(target), f"create database {restored}")
        dumped = subprocess.run(["docker", "exec", target, "pg_dump", "-U", "postgres", "-Fc", database(erp)],
                                capture_output=True, check=True).stdout
        subprocess.run(["docker", "exec", "-i", target, "pg_restore", "-U", "postgres", "--exit-on-error", "-d",
                        restored], input=dumped, capture_output=True, check=True)
        url = _url(target, restored)
        same = ["select pg_get_viewdef('raw_erp.customers__history'::regclass)",
                "select relacl::text from pg_class where oid = 'raw_erp.customers__history'::regclass",
                "select col_description('raw_erp.customers__log'::regclass, 2)",  # _op
                'select * from _rowvioli.columns order by "column"',
                "select * from _rowvioli.columns__log order by _loaded_at, \"column\"",
                "select * from _rowvioli.columns__history order by \"column\", _valid_from",
                "select * from raw_erp.customers__history order by customer_no, _valid_from"]
        for query in same:
            assert _query(url, query) == erp.target(query), query
        assert erp.target("select col_description('raw_erp.customers__log'::regclass, 2) like '%tenant%'") == [
            (True,)]
        # the program against the restored target: a change of columns, and the record and the log still replay
        erp.target_url = url
        erp.source("alter table customers drop column amount; update customers set label = 'L' where customer_no = 2")
        again(erp)
        assert columns(erp) == ["customer_no", "label", "tenant"]
        assert _query(url, f"select has_table_privilege('{role}', 'raw_erp.customers__history', 'select')") == [
            (True,)]
        replays(erp)
        log_replays(erp)
        assert rows(erp.target, "select customer_no, label from raw_erp.customers") == rows(
            erp.source, "select customer_no, label from customers")
    finally:
        _query(_url(target), f"drop database if exists {restored} with (force)")
        _query(original, f"drop owned by {role}")
        _query(_url(target), f"drop role {role}")
