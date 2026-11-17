"""Mistakes named at run: key columns, types, pause, names, variables, reasons, pooler, schema (shakedown ticket 05)."""
import pytest

from test_checks import failed
from test_rest import api, load, reason  # noqa: F401 (api is a fixture)
from test_secrets import lab
from test_run import apply, definition, erp, ok, run  # noqa: F401 (erp is a fixture)


def test_a_numeric_the_target_cannot_hold_fails_with_the_cause_and_no_path(erp):
    erp.source("create table nn (id int primary key, v numeric)")
    erp.source("insert into nn values (1, 'NaN')")
    apply(erp, definition(erp, '"public.nn" = { key = ["id"] }\n'))
    why = failed(erp)
    assert "not a valid decimal" in why and "\n" not in why and "Traceback" not in why and ".py" not in why, why


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
    assert "table public.customers has no column idd; it has: customer_no, name, city" in reason
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


def test_a_worker_without_create_on_the_database_loads_into_a_precreated_schema(erp):
    db = erp.target_url.rsplit("/", 1)[1]
    for statement in ("create schema raw_erp", "create role loader login password 'x'",
                      "grant all on schema _rowvioli, raw_erp to loader",
                      "grant all on all tables in schema _rowvioli to loader",
                      "grant all on all sequences in schema _rowvioli to loader",
                      "revoke create on schema public from public", f"revoke create on database {db} from public"):
        erp.target(statement)
    url = erp.target_url.replace("postgres:x@", "loader:x@")
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
