"""Checks, failure reasons and secrets (spec tests 15, 16, 17, 18)."""
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
    ("alter table customers add column phone text", "columns differ"),
    ("alter table customers alter customer_no type bigint", "columns differ"),
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


def test_the_password_appears_nowhere_when_the_driver_quotes_it(secret):
    garbled = "Prozent%zz-4711"  # libpq rejects the URL and quotes the token: invalid percent-encoded token
    out = [apply_with(secret, garbled), secret.run("run", "erp")]
    assert out[-1].returncode == 1
    assert "percent-encoded" in secret.target("select reason from _rowvioli.runs")[0][0]
    assert leaks(secret, garbled, *out) == []
