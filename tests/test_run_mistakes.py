"""Mistakes named at run: key columns, types, pause, names, variables, reasons, pooler, schema (shakedown ticket 05)."""
from test_checks import failed
from test_run import apply, definition, erp, ok, run  # noqa: F401 (erp is a fixture)


def test_a_key_column_the_source_does_not_have_fails_naming_it_and_the_columns_there_are(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["idd"] }\n'))
    reason = failed(erp)
    assert "table public.customers has no column idd; it has: customer_no, name, city" in reason
    assert "_stage" not in reason


def test_an_unknown_connector_type_lists_the_installed_ones(erp):
    apply(erp, definition(erp).replace('type = "postgres"', 'type = "postgress"'))
    reason = failed(erp)
    assert "postgress" in reason and "postgres" in reason.split("installed:")[1]


def test_run_says_on_stderr_that_tables_wait_out_their_pause_and_stdout_is_unchanged(erp):
    apply(erp, definition(erp, '"public.gone" = { key = ["id"] }\n'))
    assert run(erp)[0] == 1
    r = erp.run("run")
    assert r.returncode == 0 and r.stdout.strip().endswith('"tables": {}}')
    [line] = [x for x in r.stderr.splitlines() if "wait" in x]
    assert "1 table " in line and "rowvioli run <source>" in line


def test_an_unknown_table_name_suggests_the_one_table_that_ends_in_it(erp):
    r = erp.run("run", "erp", "customers")
    assert r.returncode == 1 and "did you mean public.customers" in r.stderr


def test_every_missing_variable_is_named_at_once(rv):
    for command in ("run", "work"):
        r = rv.run(command, env={"ROWVIOLI_TARGET_URL": "", "ROWVIOLI_KEY_FILE": ""}, timeout=10)
        assert "ROWVIOLI_TARGET_URL" in r.stderr and "ROWVIOLI_KEY_FILE" in r.stderr, r.stderr
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
