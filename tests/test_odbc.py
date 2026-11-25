"""The `odbc` connector, tested against the PostgreSQL source through the open psqlODBC driver (spec tests 1 to 4,
stories 20 and 22). They need an ODBC driver manager with psqlODBC; tests/odbc/run.sh runs them in a container that
has both."""
import importlib.metadata
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
ENV = {"ERP_PASSWORD": "harness-pw-7"}  # the password of the harness's containers


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
    # psqlODBC describes numeric(10,2) so, and the decimal keeps it
    assert ready.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'balance'"
                        " and attrelid = 'raw_erp.customers'::regclass") == [("numeric(10,2)",)]
    assert ready.target("select * from raw_erp.customers order by 1") == [
        (1, "Anna", Decimal("2.50"), date(1990, 5, 17), datetime(2026, 11, 12, 8, 30, 15)),
        (2, "Ben", None, None, None)]
    assert ready.target("select driver_version from _rowvioli.runs") == [
        (f"arrow-odbc {importlib.metadata.version('arrow-odbc')}",)]  # story 38
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
    [(reason,)] = ready.target("select reason from _rowvioli.runs")
    assert "password authentication failed" in reason and reason.endswith("after changing a variable it reads, run "
                                                                          "apply again"), reason  # ticket 17, L1
    for value in (wrong, "Falsch", "Kenn@wort42"):
        assert leaks(ready, value, *out) == [], value


@needs_driver
def test_a_driver_that_is_not_installed_is_named_in_the_reason(ready):  # ticket 15, D2: SQLSTATE 01000
    ready.source("create table customers (customer_no int primary key)")
    erp(ready, '"public.customers" = {}', odbc_string(ready.source_url).replace(DRIVER, "NoSuchDriver"))
    assert ready.run("run", env=ENV).returncode == 1
    assert "Can't open lib 'NoSuchDriver'" in ready.target("select reason from _rowvioli.runs")[0][0]


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
    assert "install unixodbc (libodbc)" in reason and "Traceback" not in reason, reason


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


def again(rv):
    rv.target("update _rowvioli.tables set requested_at = now()")
    r = rv.run("run", "erp", env=ENV)
    assert r.returncode == 0, r.stdout


@needs_driver
def test_a_column_goes_and_comes_widens_changes_family_is_renamed_and_the_key_changes_through_odbc(ready):
    """Decision 54 through a driver that describes the columns itself: every change of shape, the log replays."""
    from test_columns_go_and_come import columns, log_replays
    ready.source("create table t (id int primary key, alt int not null, v int, city text);"
                 "insert into t select g, g + 100, g, 'c' || (g % 7) from generate_series(1, 30) g")
    erp(ready, '"public.t" = { key = ["id"] }')
    again(ready)
    log, last = "raw_erp.t__log", 'select _op, "column", "by" from _rowvioli.columns__log where _run = (select ' \
                                  'max(run) from _rowvioli.runs) order by 2, 1'
    ready.source("alter table t drop column city")  # gone
    again(ready)
    assert columns(ready, "raw_erp.t") == ["id", "alt", "v"] and "city" in columns(ready, log)
    ready.source("alter table t add column city text; update t set city = 'c' || (id % 7)")  # back, its family
    again(ready)
    ready.source("alter table t alter v type bigint; update t set v = 10000000000 where id = 1")  # widened
    again(ready)
    assert ready.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'v' and attrelid "
                        "in ('raw_erp.t'::regclass, 'raw_erp.t__log'::regclass)") == [("bigint",), ("bigint",)]
    ready.source("alter table t alter v type text using v::text || 'x'")  # another family
    again(ready)
    [(run,)] = ready.target("select max(run) from _rowvioli.runs")
    assert f"v__{run}" in columns(ready, log)
    ready.source("alter table t rename city to town")  # proven by 30 rows, 7 values
    again(ready)
    assert ready.target(last) == [("D", "city", "source"), ("I", "town", "source")]
    erp(ready, '"public.t" = { key = ["alt"] }')  # another key
    again(ready)
    assert ready.target("select count(*) filter (where _op = 'D'), count(*) filter (where _op = 'I') from "
                        f"{log} where _run = (select max(run) from _rowvioli.runs)") == [(30, 30)]
    log_replays(ready, "raw_erp.t")


@needs_driver
@pytest.mark.parametrize("column, said", [
    ("body::int", "a statement raised an error (SQLSTATE 22P02) in the source, reading public.v;"), ("body::date", "a statement raised an error (SQLSTATE 22007) in the source, reading public.v;"),
    ("(body || '1e40')::float8::numeric(40, 0)", "a statement raised an error (SQLSTATE 22003) in the source, reading public.v;"),
    ("guard(body)", "a function raised an error (SQLSTATE P0001) in the source"),
    # arrow-odbc's own, for a numeric beyond the 28 digits psqlODBC describes: it names no value
    ("(body || '1e40')::numeric", "public.v: A value (at least one) is too large to be written into the allocated buffer")])
def test_a_value_the_source_or_the_driver_cannot_convert_stays_out_of_the_reason(ready, column, said):
    """Decision 54, item 8, through a driver whose message words the value its own way (psqlODBC appends a ;)."""
    ready.source("create function guard(b text) returns text language plpgsql as $$ begin if b <> '' then "
                 "raise exception 'bad row %', b; end if; return b; end $$")
    ready.source(f"create table t (id int primary key, body text); insert into t values (1, '');"
                 f"create view v as select id, {column} as n from t")
    erp(ready, '"public.v" = { key = ["id"] }')
    ready.source("update t set body = '4711'" if "1e40" in column else "update t set body = 'Secret4711'")
    r = ready.run("run", "erp", env=ENV)
    assert r.returncode == 1
    assert said in ready.target("select reason from _rowvioli.runs")[0][0]
    for value in ("Secret4711", "4711"):
        assert leaks(ready, value, r) == [], value


@needs_driver
def test_arrow_odbcs_own_message_of_a_value_keeps_what_comes_before_the_value():
    """Decision 54, item 8: psqlODBC delivers no value arrow-odbc cannot hold (invalid bytes arrive replaced, and
    'infinity' as a timestamp), so its two messages that end in the value are tried on their words."""
    from rowvioli.connectors.odbc import without_value
    for message, kept in [("Timestamp is not representable in arrow: 9999-12-31 23:59:59.9999999\nTimestamps with "
                           "nanoseconds precision are represented using a signed 64 Bit integer.",
                           "Timestamp is not representable in arrow"),
                          ("Datasource returned invalid UTF-8. Lossy representation of value: Secret\ufffd",
                           "Datasource returned invalid UTF-8. Lossy representation of value")]:
        assert str(without_value(OSError(message), "dbo.t")) == str(without_value(
            OSError("External error: " + message), "dbo.t")) == f"dbo.t: {kept}"
    record = RuntimeError("ODBC emitted an error calling 'SQLFetch': State: 22P02, Native error: 1, Message: x")
    assert without_value(record, "dbo.t") is record


@needs_driver
def test_a_double_arrives_whole_and_a_boolean_as_one_with_the_drivers_setting(ready):
    """psqlODBC describes float8 with a precision of 17, which arrow-odbc took for a single: 0.1234567890123456
    arrived as 0.12345679 and 1e300 as Infinity (host H2). Its booleans are text unless BoolsAsChar=0."""
    ready.source("create table t (id int primary key, f float8, r real, b bool);"
                 "insert into t values (1, 0.1234567890123456, 0.5, true), (2, 1e300, null, false)")
    erp(ready, '"public.t" = { key = ["id"] }', odbc_string(ready.source_url) + ";BoolsAsChar=0")
    r = ready.run("run", env=ENV)
    assert r.returncode == 0, r.stdout
    assert ready.target("select column_name, data_type from information_schema.columns where table_schema = "
                        "'raw_erp' and table_name = 't' order by ordinal_position") == [
        ("id", "integer"), ("f", "double precision"), ("r", "double precision"), ("b", "boolean")]
    assert ready.target("select id, f, r, b from raw_erp.t order by 1") == [
        (1, 0.1234567890123456, 0.5, True), (2, 1e300, None, False)]


@needs_driver
@pytest.mark.parametrize("value", ["4713-01-01 BC", "-infinity"])
def test_a_timestamp_the_targets_type_cannot_hold_names_the_column_and_the_way_out(ready, value):
    """psqlODBC delivers 4713 BC a year early and -infinity as the year -9999, before the least timestamp of
    Postgres, which refuses the row in staging."""
    ready.source(f"create table t (id int primary key, ts timestamp); insert into t values (1, '{value}')")
    erp(ready, '"public.t" = { key = ["id"] }')
    assert failed(ready, "erp") == ("public.t: column ts has a value its type in the target, timestamp without time "
                                    "zone, cannot hold (SQLSTATE 22008); cast it in a view of the source or change it "
                                    "there")


@needs_driver
@pytest.mark.parametrize("value", ["infinity", "-infinity"])
def test_a_date_of_infinity_the_driver_gives_as_no_date_fails_naming_the_column_and_others_load(ready, value):
    """psqlODBC gives a date's infinity and -infinity as the text 0000-00-00, which arrived as the day of the run
    (ticket 16); the connector reads dates as text and stops where one is no date (ticket 17, T1)."""
    ready.source("create table t (id int primary key, d date); insert into t values (1, '2024-02-29'), (2, null)")
    erp(ready, '"public.t" = { key = ["id"] }')
    assert run(ready, "erp")[0] == 0
    assert ready.target("select id, d from raw_erp.t order by 1") == [(1, date(2024, 2, 29)), (2, None)]
    assert ready.target("select data_type from information_schema.columns where table_name = 't' and "
                        "column_name = 'd'") == [("date",)]
    ready.source(f"insert into t values (3, '{value}')")
    ready.target("update _rowvioli.tables set requested_at = now()")
    assert failed(ready, "erp") == ("public.t: column d has a date the driver gives as no date, as psqlODBC gives "
                                    "infinity and -infinity; cast it in a view of the source")
