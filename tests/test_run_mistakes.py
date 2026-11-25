"""Mistakes named at run: key columns, types, pause, names, variables, reasons, pooler, schema (shakedown ticket 05)."""
import subprocess

import psycopg
import pytest

from conftest import HOST, _query, _url, until
from test_checks import MISSING, failed
from test_rest import api, load, reason  # noqa: F401 (api is a fixture)
from test_secrets import lab
from test_run import apply, definition, erp, ok, run  # noqa: F401 (erp is a fixture)


# whatever Arrow's message: `The string 'nan' is not a valid decimal256 number`, `Decimal value does not fit in
# precision 76`
@pytest.mark.parametrize("value, shown, has", [
    ("NaN", "'nan'", "NaN or Infinity, which no decimal holds"),
    ("-Infinity", "'-infinity'", "NaN or Infinity, which no decimal holds"),
    ("1e39", "1" + "0" * 39, "a value of more than 38 digits before or after the point, the most a numeric without "
                             "precision holds here"),
    # Arrow's cast wraps a value this long without an error: it arrived as 0 with the run ok
    ("1.5e400", "15" + "0" * 30, "a value of more than 38 digits before or after the point, the most a numeric "
                                 "without precision holds here")])
def test_a_numeric_the_target_cannot_hold_fails_with_the_cause_and_no_path(erp, value, shown, has):
    erp.source("create table nn (id int primary key, v numeric)")
    erp.source(f"insert into nn values (1, '{value}')")
    apply(erp, definition(erp, '"public.nn" = { key = ["id"] }\n'))
    why = failed(erp)
    assert f"public.nn: column v has {has}; cast it in a view of the source" == why \
        and shown not in why.lower() and "Traceback" not in why and ".py" not in why, why


@pytest.mark.parametrize("type", ["timestamp", "timestamptz", "timestamp[]"])
def test_a_timestamp_of_infinity_fails_naming_the_column_and_minus_infinity_loads(erp, type):
    """The driver reads infinity as a number it cannot write again; -infinity and a date's infinity it can."""
    erp.source(f"create table inf (id int primary key, ts {type}, d date)")
    value = "'{{{}}}'" if type.endswith("[]") else "'{}'"
    erp.source(f"insert into inf values (1, {value.format('-infinity')}, 'infinity'), "
               f"(2, {value.format('-infinity')}, '-infinity')")
    apply(erp, definition(erp, '"public.inf" = { key = ["id"] }\n'))
    ok(erp)
    text = "select id, ts::text, d::text from {} order by 1"
    assert erp.target(text.format("raw_erp.inf")) == erp.source(text.format("inf"))
    erp.source(f"update inf set ts = {value.format('infinity')} where id = 2")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ("public.inf: column ts has infinity, which the driver cannot write into a "
                           f"{type.removesuffix('[]')} of the target; cast it in a view of the source")


def test_a_numeric_whose_values_fit_loads_whatever_its_digits_before_the_point(erp):
    if int(erp.source("show server_version_num")[0][0]) < 150000:
        pytest.skip("a numeric's scale below 0 or above its precision needs Postgres 15 in the source")
    # a precision equal to the scale has no digit before the point but the 0 Postgres writes; beyond 76 digits no
    # decimal has the precision, so the column is read as an unconstrained one
    columns = {"a": ("numeric(2,2)", "-0.99"), "b": ("numeric(3,5)", "0.00123"), "c": ("numeric(1000,0)", "-5"),
               "d": ("numeric", "-0012345678901234567890123456789012345678.5"), "e": ("numeric(38,0)", "9" * 38)}
    erp.source(f"create table nn (id int primary key, {', '.join(f'{c} {t}' for c, (t, _) in columns.items())})")
    erp.source(f"insert into nn values (1, {', '.join(v for _, v in columns.values())})")
    apply(erp, definition(erp, '"public.nn" = { key = ["id"] }\n'))
    ok(erp)
    text = f"select {', '.join(f'{c}::text' for c in columns)} from {{}}"
    assert erp.target(text.format("raw_erp.nn")) == erp.source(text.format("nn"))


@pytest.mark.parametrize("value, type, state", [
    ("Secret3", "int", "22P02"), ("3000000000", "int", "22003"), ("2024-13-45 Secret4", "date", "22008"),
    ("1e999", "float8", "22003")])
def test_a_value_the_source_cannot_convert_stays_out_of_the_reason(erp, value, type, state):
    erp.source("create table raw (id int primary key, v text)")
    erp.source(f"insert into raw values (1, '{value}')")
    erp.source(f"create view cast_view as select id, v::{type} as v from raw")
    apply(erp, definition(erp, '"public.cast_view" = { key = ["id"] }\n'))
    r = erp.run("run")
    assert r.returncode == 1
    why = erp.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert why == (f"a statement raised an error (SQLSTATE {state}) in the source, reading public.cast_view; its message "
                   "may hold a row's values, so it is left out here: the source's server log or a trace has it")
    assert value not in r.stdout + r.stderr


def test_a_table_the_source_does_not_have_is_said_in_the_programs_own_words(erp):  # ticket 17, L2, G2
    apply(erp, definition(erp, '"public.customers2" = {}\n'))  # misspelt, which apply cannot know
    assert failed(erp) == MISSING.format(table="public.customers2", state="42P01")


def test_a_failed_rest_path_stays_in_the_reason(api):
    load(api, 'a = { key = ["station"], path = "/v1/items", columns = { station = "text" } }')
    assert "/v1/items answered 404" in reason(api)


def test_a_first_load_of_a_connector_that_delivers_no_batch_names_that(erp):
    lab(erp, "nothing = true")
    why = failed(erp, "lab")
    assert why == "the connector delivered nothing, not even the columns"


def test_an_exception_without_a_message_names_its_type(erp):
    lab(erp, 'fail = "empty"')
    assert failed(erp, "lab") == "the driver gave no message while reading the source (KeyError)"


def test_a_key_column_the_source_does_not_have_fails_naming_it_and_the_columns_there_are(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["idd"] }\n'))
    reason = failed(erp)
    assert ("table public.customers has no column idd, which the key names: give the table a key of the columns it "
            "has: customer_no, name, city") in reason
    assert "_stage" not in reason


def test_an_unknown_connector_type_lists_the_installed_ones(erp):
    apply(erp, definition(erp).replace('type = "postgres"', 'type = "weather"'))  # a near miss fails apply
    reason = failed(erp)
    assert "weather" in reason and "postgres" in reason.split("installed:")[1]


def test_the_first_mirror_needs_only_the_target_url(rv):
    rv.source("create table t (id int primary key, v text); insert into t values (1, 'a')")
    rv.definition({"erp.toml": definition(rv, '"public.t" = { key = ["id"] }\n')})
    env = {"ROWVIOLI_KEY_FILE": ""}
    for args in (["key", "new"], ["apply", "--init"], ["run"], ["status"]):
        r = rv.run(*args, env=env)
        assert r.returncode == 0, (args, r.stderr)
    assert rv.target("select id, v from raw_erp.t") == [(1, "a")]


def test_a_changed_target_table_is_loaded_by_the_next_run(erp):
    ok(erp)
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], target_table = "clients" }\n'))
    code, answer = run(erp)
    assert code == 0 and list(answer["tables"]) == ["raw_erp.clients"], answer


def test_run_says_on_stderr_that_tables_wait_out_their_pause_and_stdout_is_unchanged(erp):
    apply(erp, definition(erp, '"public.gone" = { key = ["id"] }\n'))
    assert run(erp)[0] == 1
    r = erp.run("run")
    assert r.returncode == 0 and r.stdout.strip().endswith('"tables": {}}')
    [line] = [x for x in r.stderr.splitlines() if "wait" in x]
    assert "1 table waits out its pause" in line and "rowvioli run <source>" in line


def test_an_unknown_table_name_suggests_the_one_table_that_ends_in_it(erp):
    r = erp.run("run", "erp", "customers")
    assert r.returncode == 1 and "did you mean public.customers" in r.stderr


def test_a_missing_target_url_is_named(rv):
    r = rv.run("status", env={"ROWVIOLI_TARGET_URL": ""}, timeout=10)
    assert "ROWVIOLI_TARGET_URL" in r.stderr


def test_a_reason_is_one_line_without_wrapper_traceback_or_path(erp):
    apply(erp, definition(erp, '"public.gone" = { key = ["id"] }\n'))
    reason = failed(erp)
    assert "public.gone" in reason, reason
    assert "\n" not in reason and "Traceback" not in reason and "/" not in reason, reason
    for wrapper in ("NOT_FOUND:", "IO:", "nanoarrow", "Failed to prepare query:"):
        assert wrapper not in reason, reason


def test_a_run_on_a_direct_connection_passes_the_pooler_check(erp):
    ok(erp)


POOLER = "edoburu/pgbouncer:v1.26.1-p0"


def reachable(url):
    try:
        psycopg.connect(url, connect_timeout=1).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def pooler(erp, servers, request):
    """A PgBouncer in front of the test's target database, in the mode given; returns the target URL through it. The
    pooler has no other client, so it hands out the same server connection each time. Its image (30 MB) is not
    pulled by the tests: without it they are skipped."""
    if subprocess.run(["docker", "image", "inspect", POOLER], capture_output=True).returncode:
        pytest.skip(f"docker pull {POOLER} to run it")
    db = erp.target_url.rsplit("/", 1)[1]
    ip = subprocess.run(["docker", "inspect", "-f", "{{.NetworkSettings.Networks.bridge.IPAddress}}", servers["target"]],
                        check=True, capture_output=True, text=True).stdout.strip()
    name = f"{servers['target']}-pooler-{db}"
    mode, _, clients = request.param.partition(" with ")  # "session with 1": a pooler that takes one client
    subprocess.run(["docker", "run", "-d", "--name", name, "--label", "rowvioli-test", "-e", "AUTH_TYPE=scram-sha-256",
                    "-e", f"DATABASE_URL=postgres://postgres:harness-pw-7@{ip}:5432/{db}", "-e", f"POOL_MODE={mode}",
                    *(["-e", f"MAX_CLIENT_CONN={clients}"] if clients else []),
                    "-p", "127.0.0.1::5432", POOLER], check=True, capture_output=True)
    request.addfinalizer(lambda: subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True))
    port = subprocess.run(["docker", "port", name, "5432/tcp"], check=True, capture_output=True,
                          text=True).stdout.split()[0].rsplit(":", 1)[1]
    url = f"postgresql://postgres:harness-pw-7@{HOST}:{port}/{db}"
    until(lambda: reachable(url))
    return url


@pytest.mark.parametrize("pooler", ["transaction", "session"], indirect=True)
def test_a_pooler_in_transaction_mode_is_refused_before_anything_is_claimed_and_one_in_session_mode_loads(
        erp, pooler, request):
    through = {"ROWVIOLI_TARGET_URL": pooler}
    r = erp.run("run", env=through)
    if request.node.callspec.params["pooler"] == "session":
        assert r.returncode == 0, r.stderr + r.stdout
        return
    assert r.returncode == 1 and r.stderr.endswith(
        "a connection pooler in transaction mode is in front of the target; use session mode or connect directly\n"), \
        r.stderr + r.stdout
    assert erp.target("select count(*) from _rowvioli.runs") == [(0,)]
    assert erp.run("status", env=through).returncode == 1


@pytest.mark.parametrize("pooler", ["session with 1"], indirect=True)
def test_a_command_that_finds_no_second_connection_to_spare_is_not_refused_for_it(erp, pooler):
    # the check's second connection is refused, as by a full max_connections; the command needs one
    r = erp.run("status", env={"ROWVIOLI_TARGET_URL": pooler})
    assert r.returncode == 0, r.stderr


def test_a_worker_without_create_on_the_database_loads_into_a_precreated_schema(erp):
    db = erp.target_url.rsplit("/", 1)[1]
    for statement in ("create schema raw_erp", "create role loader login password 'x'",
                      "grant all on schema _rowvioli, raw_erp to loader",
                      "grant all on all tables in schema _rowvioli to loader",
                      "grant all on all sequences in schema _rowvioli to loader",
                      "revoke create on schema public from public", f"revoke create on database {db} from public"):
        erp.target(statement)
    url = erp.target_url.replace("postgres:harness-pw-7@", "loader:x@")
    r = erp.run("run", env={"ROWVIOLI_TARGET_URL": url})
    assert r.returncode == 0, r.stdout + r.stderr
    assert erp.target("select count(*) from raw_erp.customers") == [(3,)]


@pytest.mark.parametrize("command", ["run", "work"])
def test_a_missing_key_file_stops_the_start_names_the_path_and_the_command_that_creates_it(rv, command):
    assert rv.run("init").returncode == 0
    r = rv.run(command, env={"ROWVIOLI_KEY_FILE": str(rv.dir / "nope.key")}, timeout=10)
    assert r.returncode != 0 and str(rv.dir / "nope.key") in r.stderr and "rowvioli key new" in r.stderr, r.stderr
    assert rv.target("select count(*) from _rowvioli.runs") == [(0,)]


def test_without_the_variable_the_key_file_is_worker_key_in_the_current_directory(rv):
    assert rv.run("init").returncode == 0
    r = rv.run("run", env={"ROWVIOLI_KEY_FILE": ""}, timeout=10)  # empty counts as unset
    assert r.returncode != 0 and str(rv.dir / "worker.key") in r.stderr and "rowvioli key new" in r.stderr, r.stderr
    assert rv.run("key", "new").returncode == 0
    assert rv.run("run", env={"ROWVIOLI_KEY_FILE": ""}, timeout=10).returncode == 0


def test_a_missing_key_file_says_to_copy_the_key_and_that_key_new_is_for_a_new_target(rv):
    r = rv.run("run", env={"ROWVIOLI_KEY_FILE": ""}, timeout=10)
    assert r.returncode != 0 and "copy worker.key from where `rowvioli key new` was run" in r.stderr, r.stderr
    assert "only for a new target" in r.stderr


def test_a_key_file_that_is_a_directory_or_unreadable_stops_the_start_with_the_reason_of_the_system(rv):
    (rv.dir / "adir").mkdir()
    for command in ("run", "work"):
        r = rv.run(command, env={"ROWVIOLI_KEY_FILE": str(rv.dir / "adir")}, timeout=10)
        assert r.returncode != 0 and "Is a directory" in r.stderr and "copy worker.key" not in r.stderr, r.stderr
    (rv.dir / "secret.key").write_text("x")
    (rv.dir / "secret.key").chmod(0)
    r = rv.run("run", env={"ROWVIOLI_KEY_FILE": str(rv.dir / "secret.key")}, timeout=10)
    assert r.returncode != 0 and "Permission denied" in r.stderr, r.stderr


def test_a_wrong_key_names_both_ways_out_and_keeps_the_key_id(erp):
    (erp.dir / "worker.key").unlink()
    (erp.dir / "worker.pub").unlink()
    assert erp.run("key", "new").returncode == 0  # what a second machine does, following the wrong advice
    reason = failed(erp)
    assert "holds no private key " in reason and "not the key the definition was applied with" in reason, reason
    assert "worker.key that belongs to the worker.pub next to the definition" in reason, reason
    assert "apply again with this key's worker.pub" in reason, reason


def test_a_renamed_table_is_new_again_without_age_or_old_reason_and_a_failure_waits_one_minute(erp):
    apply(erp, definition(erp, '"public.gone" = { key = ["id"] }\n'))
    failed(erp)
    erp.target("update _rowvioli.tables set loaded_at = now() - interval '1 hour' where source_table = 'public.gone'")
    apply(erp, definition(erp, '"public.gone" = { key = ["id"], target_table = "other" }\n'))
    assert erp.target("select status, age is null, reason is null, due_at <= now() from _rowvioli.status "
                      "where source_table = 'public.gone'") == [("new", True, True, True)]
    assert erp.target("select attempts, loaded_at is null from _rowvioli.tables "
                      "where source_table = 'public.gone'") == [(0, True)]
    failed(erp)
    assert erp.target("select attempts, due_at > now() + interval '30 seconds', due_at <= now() + interval '61 seconds' "
                      "from _rowvioli.status where source_table = 'public.gone'") == [(1, True, True)]


def test_a_request_survives_the_rename(erp):
    ok(erp)
    erp.target("update _rowvioli.tables set requested_at = now() + interval '1 day'")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], target_table = "clients" }\n'))
    assert erp.target("select requested_at is not null from _rowvioli.tables") == [(True,)]


def test_run_with_a_table_where_the_source_belongs_says_so_and_names_the_source_when_one_holds_it(erp):
    r = erp.run("run", "customers")
    assert r.returncode == 1 and "customers is no source" in r.stderr
    assert "the first name of `run` is a source" in r.stderr
    assert "did you mean `rowvioli run erp customers`" in r.stderr, r.stderr
    r = erp.run("run", "nothing")
    assert r.returncode == 1 and "nothing is no source" in r.stderr and "did you mean" not in r.stderr


def test_a_line_break_in_a_column_name_is_written_as_a_question_mark_and_the_reason_goes_on(erp):
    erp.source('alter table customers add column "a\nb" text')
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], log = false }\n'))
    ok(erp)
    erp.source('alter table customers drop column "a\nb"')
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)  # the way out with Unicode escapes, so that it works when pasted (ticket 15, X3)
    assert reason == ("column a?b is missing in the source, and no change log keeps its values, "
                      'so a person drops it: ALTER TABLE "raw_erp"."customers" DROP COLUMN U&"a\\000Ab"')
    erp.target(reason.rpartition(": ")[2])
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)



def latin1(server, db):
    """The test's database on that server made again in LATIN1."""
    _query(_url(server), f"drop database {db}")
    _query(_url(server), f"create database {db} encoding latin1 template template0 lc_collate 'C' lc_ctype 'C'")

def test_a_latin1_target_stores_the_sources_text_and_refuses_one_it_has_no_character_for(rv, servers):
    """The session asks for UTF8, whatever the target database's encoding (host H1: `Müller` became `MÃ¼ller`)."""
    db = rv.target_url.rsplit("/", 1)[1]  # the test's database, made again in LATIN1
    latin1(servers["target"], db)
    assert rv.run("init").returncode == 0 and rv.run("key", "new").returncode == 0
    rv.source("create table customers (customer_no int primary key, name text);"
              "insert into customers values (1, 'Müller')")
    apply(rv, definition(rv).replace('max_age = "1h"', 'max_age = "1h"\ntarget_schema = "raw_ü"'))
    ok(rv)
    assert rv.target('select name from "raw_ü".customers') == [("Müller",)]
    r = rv.run("status")
    assert r.returncode == 0 and "raw_ü.customers" in r.stdout, r.stderr
    rv.source("update customers set name = 'Ω'")
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert failed(rv) == (
        "public.customers: column name has a value its type in the target, text, cannot hold (SQLSTATE 22P05); cast "
        "it in a view of the source or change it there")


def test_a_latin1_source_delivers_its_text(rv, servers):
    latin1(servers["source"], rv.source_url.rsplit("/", 1)[1])
    assert rv.run("init").returncode == 0 and rv.run("key", "new").returncode == 0
    rv.source("create table customers (customer_no int primary key, name text);"
              "insert into customers values (1, 'Müller')")
    apply(rv, definition(rv))
    ok(rv)
    assert rv.target("select name from raw_erp.customers") == [("Müller",)]
