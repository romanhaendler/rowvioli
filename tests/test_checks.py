"""Checks, schema changes, failure reasons and secrets (spec tests 12, 13, 15, 16, 17, 18)."""
import time

import psycopg
import pytest

from test_run import apply, definition, erp, ok, rows, run  # noqa: F401 (erp is a fixture)



def failed(rv, *args):
    """`run` that must fail one table; returns its reason as answered, in the status and in `runs`."""
    code, answer = run(rv, *args)
    assert code == 1, answer
    [reason] = [a["reason"] for a in answer["tables"].values() if a["status"] == "failed"]
    [(status, in_status)] = rv.target("select status, reason from _rowvioli.status where status = 'failed'")
    assert in_status == reason
    assert rv.target("select status, reason from _rowvioli.runs order by run desc limit 1") == [("failed", reason)]
    return reason


MIRROR = "select * from raw_erp.customers"


@pytest.mark.parametrize("change, expected", [
    ("insert into customers values (4, 'Dora', null); alter table customers drop constraint customers_pkey;"
     " insert into customers values (1, 'Anna2', null)", "occurs twice"),
    ("alter table customers drop constraint customers_pkey; alter table customers alter customer_no drop not null;"
     " insert into customers values (null, 'Nobody', null)", "is null"),
    ("delete from customers", "zero rows"),
    ("delete from customers where customer_no <> 1", "67 % of the rows would be deleted"),
    ("alter table customers alter customer_no type text", "column customer_no has changed its type from integer to "
     "te***t, a type of another family in the key, so a row before cannot be told from one after: give the table "
     "another target_table"),  # cases C8; the harness's password is x, which a reason hides
    ("alter table customers add column _op text", "column _op is a name of the change log"),
    ("alter table customers add column _run int", "column _run is a name of the change log"),
])
def test_a_check_fails_the_run_and_leaves_the_mirror_unchanged(erp, change, expected):
    ok(erp)
    before = rows(erp.target, MIRROR)
    for statement in change.split("; "):
        erp.source(statement)
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert expected in failed(erp)
    assert rows(erp.target, MIRROR) == before


def test_a_key_that_differs_from_the_mirrors_primary_key_fails_the_run(erp):
    ok(erp)
    before = rows(erp.target, MIRROR)
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "key" in failed(erp)
    assert rows(erp.target, MIRROR) == before


def test_a_table_that_lost_its_key_in_the_definition_says_so_and_names_both_ways_out(erp):
    ok(erp)
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert "no key any more" in reason and "['customer_no']" in reason, reason
    assert "put the key back" in reason and "target_table" in reason, reason
    assert "[] differs" not in reason, reason


def test_a_new_source_column_appears_in_the_mirror_and_the_change_log_with_values(erp):
    ok(erp)
    erp.source("alter table customers add column phone text")
    erp.source("update customers set phone = '0228' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    # a row whose new column is null equals its mirror row, so only Anna changed
    assert erp.target("select _op, customer_no, name, phone from raw_erp.customers__log where _run = "
                      "(select max(run) from _rowvioli.runs)") == [("U", 1, "Anna", "0228")]


def test_a_new_column_waits_10s_for_a_reading_consumer_then_fails_and_loads_once_the_reader_is_done(erp):
    ok(erp)
    before = rows(erp.target, MIRROR)
    erp.source("alter table customers add column phone text")
    erp.target("update _rowvioli.tables set requested_at = now()")
    with psycopg.connect(erp.target_url) as consumer:  # a long read: its transaction holds the mirror
        consumer.execute(MIRROR)
        started = time.monotonic()
        reason = failed(erp)
        assert "lock timeout" in reason and time.monotonic() - started >= 10
    assert rows(erp.target, MIRROR) == before
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")


def test_a_table_without_a_key_fails_when_it_would_shrink_by_more_than_max_delete_share(erp):
    apply(erp, definition(erp, '"public.notes" = {}\n'))
    ok(erp)
    before = rows(erp.target, "select * from raw_erp.notes")
    erp.source("delete from notes where txt = 'a'")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "67 % of the rows would be deleted" in failed(erp)
    assert rows(erp.target, "select * from raw_erp.notes") == before


def test_max_delete_share_of_a_table_overrides_the_sources(erp):
    text = definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 0.9 }\n')
    apply(erp, text.replace('max_age = "1h"', 'max_age = "1h"\nmax_delete_share = 0.1'))
    ok(erp)
    erp.source("delete from customers where customer_no <> 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    code, answer = run(erp)
    assert code == 0, answer
    assert answer["tables"]["raw_erp.customers"]["deleted"] == 2



def test_an_unknown_connector_type_fails_with_a_reason_naming_the_type_and_the_worker(erp):
    apply(erp, definition(erp).replace('type = "postgres"', 'type = "nosuch"'))
    reason = failed(erp)
    [(worker,)] = erp.target("select worker from _rowvioli.runs")
    assert "nosuch" in reason and worker in reason



def test_a_worker_with_the_wrong_private_key_fails_the_run_with_a_reason(erp):
    (erp.dir / "worker.key").rename(erp.dir / "old.key")
    (erp.dir / "worker.pub").rename(erp.dir / "old.pub")
    assert erp.run("key", "new").returncode == 0  # the connection stays sealed for old.pub
    reason = failed(erp)
    [(worker,)] = erp.target("select worker from _rowvioli.runs")
    assert "decrypt" in reason and worker in reason


PASSWORD, WRONG = "Sesam-0815-oeffne-dich", "Falsch-4711-geheim"


@pytest.fixture
def secret(erp):
    """erp reading the source as a role whose password is a placeholder, plus a second source crm."""
    role = "reader_" + erp.source_url.rsplit("/", 1)[1]
    erp.source(f"create role {role} login password '{PASSWORD}'")
    erp.source(f"grant select on all tables in schema public to {role}")
    url = erp.source_url.replace("postgres:x@", f"{role}:$ERP_PASSWORD@")
    text = definition(erp).replace(erp.source_url, url)
    erp.definition({"erp.toml": text, "crm.toml": text.replace("[erp", "[crm")})
    return erp


def apply_with(rv, password):
    r = rv.run("apply", "sources", env={"ERP_PASSWORD": password})
    assert r.returncode == 0, r.stderr
    return r


def leaks(rv, password, *outputs):
    """Every place a user sees text: reasons in the status and in `runs`, and the output of commands."""
    seen = [r.stdout + r.stderr for r in outputs]
    seen += [str(x) for x in rv.target("select reason from _rowvioli.tables union all select reason from _rowvioli.runs")]
    return [s for s in seen if password in s]



def test_the_stored_connection_does_not_contain_the_password(secret):
    apply_with(secret, PASSWORD)
    assert secret.target("select count(*) from _rowvioli.sources where position(convert_to(%s, 'UTF8') in connection) > 0",
                         [PASSWORD]) == [(0,)]



def test_a_ciphertext_copied_to_another_source_is_rejected(secret):
    apply_with(secret, PASSWORD)
    secret.target("update _rowvioli.sources set connection = (select connection from _rowvioli.sources where name = 'erp')"
                  " where name = 'crm'")
    assert "another source" in failed(secret, "crm")
    assert run(secret, "erp")[0] == 0


def test_two_sources_whose_sealed_connections_are_swapped_both_fail(secret):
    apply_with(secret, PASSWORD)
    secret.target("update _rowvioli.sources set connection = case name when 'erp' then (select connection from"
                  " _rowvioli.sources where name = 'crm') else (select connection from _rowvioli.sources"
                  " where name = 'erp') end")
    code, answer = run(secret)
    assert code == 1
    assert [a["reason"].count("sealed for another source") for a in answer["tables"].values()] == [1, 1]



def test_the_password_appears_nowhere_when_a_run_fails(secret):
    out = [apply_with(secret, PASSWORD)]
    apply_with(secret, PASSWORD)
    secret.definition({"erp.toml": (secret.dir / "sources" / "erp.toml").read_text()
                       .replace('"public.customers"', '"public.missing"')})
    out.append(apply_with(secret, PASSWORD))
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    assert leaks(secret, PASSWORD, *out) == []



def test_the_password_appears_nowhere_when_the_source_refuses_the_login(secret):
    out = [apply_with(secret, WRONG), secret.run("run", "erp")]
    assert out[-1].returncode == 1
    assert "password authentication failed" in secret.target("select reason from _rowvioli.runs")[0][0]
    assert leaks(secret, WRONG, *out) == []



def test_a_password_with_at_and_percent_written_plainly_loads_and_leaks_nowhere_when_refused(secret):
    plain = "Sesam@Torweg%zz-0815"
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{plain}'")
    out = [apply_with(secret, plain), secret.run("run", "erp")]
    assert out[-1].returncode == 0, out[-1].stdout + out[-1].stderr
    secret.source(f"alter role {role} password '{WRONG}'")
    secret.target("update _rowvioli.tables set requested_at = now()")
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    reason = secret.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert "password authentication failed" in reason
    for part in (plain, "Sesam", "Torweg", "zz-0815", "Sesam%40Torweg%25zz-0815"):
        assert leaks(secret, part, *out) == [], part


def test_a_password_from_a_variable_with_at_slash_and_colon_is_encoded_and_loads(secret):
    odd = "Se@sam/Tor:weg-0815"
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{odd}'")
    apply_with(secret, odd)
    assert run(secret, "erp")[0] == 0


@pytest.mark.parametrize("plain", ["Sesam[Torweg-0815", "Sesam]Torweg[0815"])
def test_a_password_with_a_bracket_written_plainly_gets_as_far_as_the_connection_and_leaks_nowhere(secret, plain):
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{plain}'")
    text = (secret.dir / "sources" / "erp.toml").read_text().replace("$ERP_PASSWORD", plain)
    secret.definition({"erp.toml": text, "crm.toml": text.replace("[erp", "[crm")})
    out = [secret.run("apply", "sources")]
    assert out[-1].returncode == 0, out[-1].stderr
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 0, out[-1].stdout + out[-1].stderr
    secret.source(f"alter role {role} password '{WRONG}'")
    secret.target("update _rowvioli.tables set requested_at = now()")
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    reason = secret.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert "password authentication failed" in reason
    for part in (plain, "Sesam", "Torweg"):
        assert leaks(secret, part, *out) == [], part


def test_a_new_empty_source_table_is_mirrored_as_an_empty_table(erp):
    erp.source("create table fresh (id int primary key, note text)")
    apply(erp, definition(erp, '"public.fresh" = { key = ["id"] }\n'))
    code, answer = run(erp)
    assert code == 0, answer
    assert erp.target("select count(*) from raw_erp.fresh") == [(0,)]


def test_an_option_postgres_does_not_know_fails_the_run_and_names_it(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], incremental = "updated" }\n'))
    assert failed(erp) == ("public.customers: the option incremental is not one of the postgres connector's; "
                           "it knows no option")


def test_an_emptied_source_publishes_when_max_delete_share_is_1(erp):
    ok(erp)
    erp.source("delete from customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "_delete_share = 1.0" in failed(erp)  # not "max_": the source's password is "x"
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 1.0 }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == []
    assert erp.target("select _op, count(*) from raw_erp.customers__log where _run = (select max(run) from "
                      "_rowvioli.runs) group by 1") == [("D", 3)]


def test_a_table_without_a_key_is_emptied_the_same_way(erp):
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    ok(erp)
    erp.source("delete from customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "_delete_share = 1.0" in failed(erp)
    apply(erp, definition(erp, '"public.customers" = { max_delete_share = 1.0 }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == []
