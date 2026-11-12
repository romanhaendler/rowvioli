"""The `odbc` connector, tested against the PostgreSQL source through the open psqlODBC driver (spec tests 1 to 4,
stories 20 and 22). They need an ODBC driver manager with psqlODBC; tests/odbc/run.sh runs them in a container that
has both."""
import shutil
import subprocess
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

import pytest

from test_checks import failed, leaks
from test_list import paste_apply_run, source
from test_run import run

try:
    import arrow_odbc
except (ImportError, OSError):  # arrow-odbc not installed, or no ODBC driver manager to load
    arrow_odbc = None

DRIVER = "PostgreSQL Unicode"
HOW = (f"needs an ODBC driver manager with the driver {DRIVER} (unixodbc and odbc-postgresql on Debian),"
       " or run tests/odbc/run.sh")
has_driver = arrow_odbc is not None and bool(shutil.which("odbcinst")) and f"[{DRIVER}]" in subprocess.run(
    ["odbcinst", "-q", "-d"], capture_output=True, text=True).stdout
needs_driver = pytest.mark.skipif(not has_driver, reason=HOW)
ENV = {"ERP_PASSWORD": "x"}  # the password of the harness's containers


def odbc_string(url, password="$ERP_PASSWORD"):
    u = urlsplit(url)
    return f"Driver={{{DRIVER}}};Server={u.hostname};Port={u.port};Database={u.path[1:]};UID=postgres;PWD={password}"


@pytest.fixture
def ready(rv):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    return rv


def erp(rv, tables, connection=None, env=ENV):
    """Applies the source erp of type odbc on the harness's source; the password is filled in from env."""
    rv.definition({"erp.toml": f"""
[erp]
type = "odbc"
max_age = "1h"
[erp.connection]
string = "{connection or odbc_string(rv.source_url)}"
[erp.tables]
{tables}"""})
    r = rv.run("apply", "sources", env=env)
    assert r.returncode == 0, r.stderr
    return r


@needs_driver
def test_a_table_is_mirrored_with_its_types_and_a_change_reaches_the_change_log(ready):
    ready.source("create table customers (customer_no int primary key, name text, balance numeric(10, 2),"
                 " born date, seen timestamp)")
    ready.source("insert into customers values (1, 'Anna', 2.50, '1990-05-17', '2026-11-12 08:30:15'),"
                 " (2, 'Ben', null, null, null)")
    erp(ready, '"public.customers" = { key = ["customer_no"] }')
    r = ready.run("run")
    assert r.returncode == 0, r.stdout
    assert ready.target("select column_name, data_type from information_schema.columns where table_schema = 'raw_erp'"
                        " and table_name = 'customers' order by ordinal_position") == [
        ("customer_no", "integer"), ("name", "text"), ("balance", "numeric"), ("born", "date"),
        ("seen", "timestamp without time zone")]
    assert ready.target("select * from raw_erp.customers order by 1") == [
        (1, "Anna", Decimal("2.50"), date(1990, 5, 17), datetime(2026, 11, 12, 8, 30, 15)),
        (2, "Ben", None, None, None)]
    ready.source("update customers set balance = 3.75 where customer_no = 2")
    r = ready.run("run", "erp")
    assert r.returncode == 0, r.stdout
    second = ready.target("select max(run) from _rowvioli.runs")[0][0]
    assert ready.target("select _op, customer_no, balance from raw_erp.customers__log where _run = %s", [second]) == [
        ("U", 2, Decimal("3.75"))]


@needs_driver
def test_list_prints_the_tables_with_their_primary_keys_that_apply_and_load(ready):
    ready.source("create table customers (customer_no int primary key, name text);"
                 "create table order_lines (line_no int, order_no int, primary key (order_no, line_no));"
                 "create table notes (body text);"
                 "insert into customers values (1, 'Anna'); insert into order_lines values (1, 7);"
                 "insert into notes values ('hello')")
    file = source(ready, "erp", "odbc", f'string = "{odbc_string(ready.source_url)}"')
    r = ready.run("list", "erp", env=ENV)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ('"public.customers" = { key = ["customer_no"] }\n'
                        '"public.notes" = {}\n'
                        '"public.order_lines" = { key = ["order_no", "line_no"] }\n')
    assert paste_apply_run(ready, file, r.stdout, ENV) == {
        "raw_erp.customers": 1, "raw_erp.notes": 1, "raw_erp.order_lines": 1}


@needs_driver
def test_a_wrong_password_fails_the_run_and_appears_nowhere(ready):
    ready.source("create table customers (customer_no int primary key)")
    wrong = "Falsch;Kenn@wort42"
    out = [erp(ready, '"public.customers" = {}', odbc_string(ready.source_url, "{$ERP_PASSWORD}"),
               {"ERP_PASSWORD": wrong}), ready.run("run")]
    assert out[-1].returncode == 1
    assert "password authentication failed" in ready.target("select reason from _rowvioli.runs")[0][0]
    for value in (wrong, "Falsch", "Kenn@wort42"):
        assert leaks(ready, value, *out) == [], value


@pytest.mark.skipif(arrow_odbc is None, reason=HOW)
@pytest.mark.parametrize("table", ["public.x'; drop table public.y; --", "public.x;drop table public.y", 'public."x"'])
def test_a_table_name_with_a_quote_or_a_semicolon_is_refused_before_any_connection(ready, table):
    # an unreachable server: a refusal that names the rule shows that no connection was even tried
    erp(ready, f'"{table.replace(chr(34), chr(92) + chr(34))}" = {{}}', odbc_string("odbc://nowhere.invalid:1/erp"))
    assert "letters, digits and underscores" in failed(ready)


@pytest.mark.skipif(arrow_odbc is not None, reason="arrow-odbc and an ODBC driver manager are installed here")
def test_without_an_odbc_driver_manager_a_source_of_type_odbc_fails_as_a_missing_connector(ready):
    erp(ready, '"public.customers" = {}')
    code, answer = run(ready)
    assert code == 1
    [reason] = [a["reason"] for a in answer["tables"].values()]
    assert reason.startswith('connector "odbc" cannot be loaded on worker ')


@needs_driver
def test_a_text_value_longer_than_the_driver_reports_fails_the_run_and_one_within_the_limit_arrives_whole(ready):
    ready.source("create table notes (id int primary key, body text);"
                 "insert into notes select 1, repeat('x', 100000)")
    erp(ready, '"public.notes" = { key = ["id"] }')  # psqlODBC reports text as 8190 bytes at most
    assert ready.run("run").returncode == 1
    erp(ready, '"public.notes" = { key = ["id"] }', odbc_string(ready.source_url) + ";MaxLongVarcharSize=1048576")
    assert ready.run("run", "erp").returncode == 0
    assert ready.target("select length(body) from raw_erp.notes") == [(100000,)]
    ready.source("update notes set body = repeat('y', 2000000)")
    assert ready.run("run", "erp").returncode == 1
    assert ready.target("select length(body) from raw_erp.notes") == [(100000,)]
