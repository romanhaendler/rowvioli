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
    assert "public.nn: column v has a value no decimal holds, such as NaN or Infinity; cast it in a view of the " \
           "source" in why and "'nan'" not in why and "Traceback" not in why and ".py" not in why, why


@pytest.mark.parametrize("value, type, says", [
    ("Secret3", "int", "invalid input synta*** for type integer"),  # x is the harness's password
    ("3000000000", "int", "out of range for type integer"),
    ("2024-13-45 Secret4", "date", "date/time field value out of range"),
    ("1e999", "float8", '"***" is out of range for type double precision')])
def test_a_value_the_source_cannot_convert_stays_out_of_the_reason(erp, value, type, says):
    erp.source("create table raw (id int primary key, v text)")
    erp.source(f"insert into raw values (1, '{value}')")
    erp.source(f"create view cast_view as select id, v::{type} as v from raw")
    apply(erp, definition(erp, '"public.cast_view" = { key = ["id"] }\n'))
    r = erp.run("run")
    assert r.returncode == 1
    why = erp.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert says in why and value not in why and value not in r.stdout + r.stderr, why


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
