"""The pause after a failed run and requests by other systems, with real runs (spec tests 11, 12)."""
from datetime import timedelta

import psycopg

from conftest import until
from test_crashes import waiting_on
from test_run import apply, definition, erp, ok, run  # noqa: F401 (erp is a fixture)


def facts(rv, table):
    return rv.target("select status, attempts, due_at - attempted_at from _rowvioli.status where source_table = %s",
                     [table])[0]


def runs(rv):
    return rv.target("select count(*) from _rowvioli.runs")[0][0]


def back(rv, minutes):
    rv.target("update _rowvioli.tables set attempted_at = attempted_at - %s", [timedelta(minutes=minutes)])


def test_a_failed_run_pauses_one_minute_doubling_never_beyond_max_age_then_loads(erp):
    apply(erp, definition(erp, '"public.gone" = { key = ["id"] }\n"public.lost" = { key = ["id"], max_age = "3m" }\n'))
    m = timedelta(minutes=1)
    assert run(erp)[0] == 1
    assert facts(erp, "public.gone") == ("failed", 1, m) and facts(erp, "public.lost") == ("failed", 1, m)
    assert run(erp)[1]["tables"] == {} and runs(erp) == 2  # not due during the pause
    back(erp, 2)
    assert run(erp)[0] == 1
    assert facts(erp, "public.gone") == ("failed", 2, 2 * m) and facts(erp, "public.lost") == ("failed", 2, 2 * m)
    back(erp, 3)
    assert run(erp)[0] == 1
    assert facts(erp, "public.gone") == ("failed", 3, 4 * m)
    assert facts(erp, "public.lost") == ("failed", 3, 3 * m)  # capped at its max_age
    assert run(erp)[1]["tables"] == {} and runs(erp) == 6
    erp.source("create table gone (id int primary key)")
    erp.source("insert into gone values (1)")
    back(erp, 4)
    assert run(erp)[1]["tables"]["raw_erp.gone"]["status"] == "ok"
    assert facts(erp, "public.gone")[:2] == ("ok", 0)


def request(rv):
    rv.target("update _rowvioli.tables set requested_at = now()")


def test_one_or_several_requests_before_a_run_cause_one_run(erp):
    ok(erp)
    for n in (1, 3):
        before = runs(erp)
        for _ in range(n):
            request(erp)
        ok(erp)
        assert runs(erp) == before + 1
    assert run(erp)[1]["tables"] == {}


def test_a_request_during_a_run_causes_one_more_run_afterwards(erp):
    ok(erp)
    request(erp)
    with psycopg.connect(erp.target_url) as holder:
        holder.execute("lock table raw_erp.customers in access exclusive mode")  # holds the run at the diff
        worker = erp.start("run")
        until(lambda: waiting_on(erp, "raw_erp.customers"))
        request(erp)
        holder.rollback()
    assert worker.wait(timeout=30) == 0
    assert runs(erp) == 1 + 2
    assert run(erp)[1]["tables"] == {}


def test_a_request_followed_by_a_failure_leaves_the_table_in_its_pause(erp):
    ok(erp)
    request(erp)
    erp.source("drop table customers")
    assert run(erp)[0] == 1
    assert facts(erp, "public.customers") == ("failed", 1, timedelta(minutes=1))
    assert run(erp)[1]["tables"] == {}
