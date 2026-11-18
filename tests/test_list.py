"""`rowvioli list`: the tables of a source as TOML, ready to paste (spec test 17)."""
import json

import pytest


@pytest.fixture
def ready(rv):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    return rv


def source(rv, name, type, connection):
    """A definition with one source and an empty tables block, as an author starts it."""
    return rv.definition({f"{name}.toml": f'[{name}]\ntype = "{type}"\nmax_age = "1h"\n'
                                          f'[{name}.connection]\n{connection}\n[{name}.tables]\n'}) / f"{name}.toml"


def paste_apply_run(rv, file, listed, env=None):
    file.write_text(file.read_text() + listed)
    r = rv.run("apply", "sources", env=env)
    assert r.returncode == 0, r.stderr
    r = rv.run("run")
    assert r.returncode == 0, r.stdout + r.stderr
    return {t: a["inserted"] for t, a in json.loads(r.stdout)["tables"].items()}


def test_list_for_postgres_prints_tables_with_primary_keys_that_apply_and_load(ready):
    ready.source("create table customers (customer_no int primary key, name text);"
                 "create table order_lines (line_no int, order_no int, primary key (order_no, line_no));"
                 "create table notes (body text);"
                 "insert into customers values (1, 'Anna'), (2, 'Ben');"
                 "insert into order_lines values (1, 7);"
                 "insert into notes values ('hello')")
    env = {"ERP_URL": ready.source_url}
    file = source(ready, "erp", "postgres", 'url = "$ERP_URL"')
    r = ready.run("list", "erp", env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ('"public.customers" = { key = ["customer_no"] }\n'
                        '"public.notes" = {}\n'
                        '"public.order_lines" = { key = ["order_no", "line_no"] }\n')
    assert paste_apply_run(ready, file, r.stdout, env) == {
        "raw_erp.customers": 2, "raw_erp.notes": 1, "raw_erp.order_lines": 1}


def test_list_for_file_prints_the_readable_files_without_keys_that_apply_and_load(ready):
    d = ready.dir / "files"
    d.mkdir()
    (d / "customers.csv").write_text("customer_no,name\n1,Anna\n2,Ben\n")
    (d / "orders.csv").write_text("order_no,customer_no\n7,1\n")  # one column would need sep
    (d / "events.jsonl").write_text('{"id": 1}\n')
    (d / "readme.txt").write_text("not a table")
    file = source(ready, "files", "file", f'path = "{d}"')
    r = ready.run("list", "files")
    assert r.returncode == 0, r.stderr
    assert r.stdout == '"customers.csv" = {}\n"events.jsonl" = {}\n"orders.csv" = {}\n'
    assert paste_apply_run(ready, file, r.stdout) == {"raw_files.customers": 2, "raw_files.events": 1,
                                                      "raw_files.orders": 1}


def test_list_needs_the_variables_of_the_listed_source_only(ready):
    ready.source("create table customers (customer_no int primary key)")
    source(ready, "erp", "postgres", 'url = "$ERP_URL"')
    source(ready, "crm", "postgres", 'url = "$CRM_URL"')  # its variable is set where crm is loaded, not here
    r = ready.run("list", "erp", env={"ERP_URL": ready.source_url})
    assert r.returncode == 0 and r.stdout == '"public.customers" = { key = ["customer_no"] }\n', r.stderr
    r = ready.run("list", "crm", env={"ERP_URL": ready.source_url})
    assert r.returncode == 1 and "variable CRM_URL is not set" in r.stderr


def test_list_fails_clearly_for_a_connector_without_tables_and_for_an_unknown_source(ready):
    source(ready, "feed", "testing", 'url = "postgresql://u:p@nowhere.invalid/x"')
    r = ready.run("list", "feed")
    assert r.returncode == 1
    assert r.stderr.strip() == "connector testing of source feed cannot list tables"
    r = ready.run("list", "erp")
    assert r.returncode == 1
    assert r.stderr.strip() == "sources has no source erp"


def test_list_without_a_definition_here_reads_the_source_from_the_target(ready):
    ready.source("create table customers (customer_no int primary key, name text);create table notes (body text)")
    env = {"ERP_URL": ready.source_url}
    file = source(ready, "erp", "postgres", 'url = "$ERP_URL"')
    wanted = ready.run("list", "erp", env=env).stdout
    assert ready.run("apply", "sources", env=env).returncode == 0  # the empty tables block: the source is in the target
    worker = ready.dir / "worker"  # no sources/ here, no ERP_URL: only the target address and the key
    worker.mkdir()
    r = ready.run("list", "erp", cwd=worker)
    assert r.returncode == 0, r.stderr
    assert r.stdout == wanted == '"public.customers" = { key = ["customer_no"] }\n"public.notes" = {}\n'
    assert paste_apply_run(ready, file, r.stdout, env) == {"raw_erp.customers": 0, "raw_erp.notes": 0}


def test_list_without_sources_here_and_without_the_target_names_both_ways(ready):
    r = ready.run("list", "erp", env={"ROWVIOLI_TARGET_URL": ""})
    assert r.returncode == 1 and r.stderr.count("\n") == 1 and "Traceback" not in r.stderr
    assert "sources/" in r.stderr and "--definition" in r.stderr and "ROWVIOLI_TARGET_URL" in r.stderr


def test_list_for_a_source_the_target_does_not_have_says_what_puts_it_there(ready):
    r = ready.run("list", "erp")
    assert r.returncode == 1 and r.stderr.count("\n") == 1
    assert "the target has no source erp" in r.stderr and "apply" in r.stderr and "empty tables block" in r.stderr


def test_list_from_the_target_with_a_missing_or_wrong_key_fails_in_one_line(ready):
    source(ready, "erp", "postgres", 'url = "$ERP_URL"')
    assert ready.run("apply", "sources", env={"ERP_URL": ready.source_url}).returncode == 0
    worker = ready.dir / "worker"  # no sources/ here
    worker.mkdir()
    r = ready.run("list", "erp", cwd=worker, env={"ROWVIOLI_KEY_FILE": str(worker / "gone.key")})
    assert r.returncode == 1 and r.stderr.count("\n") == 1 and "gone.key" in r.stderr
    assert ready.run("key", "new", cwd=worker).returncode == 0  # another key pair than the one applied with
    r = ready.run("list", "erp", cwd=worker, env={"ROWVIOLI_KEY_FILE": ""})  # falls back to worker.key here
    assert r.returncode == 1 and r.stderr.count("\n") == 1 and "Traceback" not in r.stderr
    assert "cannot be decrypted" in r.stderr and "holds no private key" in r.stderr


def test_list_with_a_definition_needs_no_target_address(ready):
    ready.source("create table customers (customer_no int primary key)")
    source(ready, "erp", "postgres", 'url = "$ERP_URL"')
    for extra in ([], ["--definition", "sources"]):
        r = ready.run("list", "erp", *extra, env={"ERP_URL": ready.source_url, "ROWVIOLI_TARGET_URL": "postgresql://u:p@w@h/x"})  # malformed, unused
        assert r.returncode == 0 and r.stdout == '"public.customers" = { key = ["customer_no"] }\n', r.stderr


def test_list_from_the_target_scrubs_the_connection_from_a_driver_error(ready):
    source(ready, "erp", "postgres", 'url = "postgresql://u:hunter2pw@nowhere.invalid/x"')
    assert ready.run("apply", "sources").returncode == 0
    worker = ready.dir / "worker"  # no sources/ here
    worker.mkdir()
    r = ready.run("list", "erp", cwd=worker)
    assert r.returncode == 1 and "\n" not in r.stderr.strip() and "hunter2pw" not in r.stderr


def test_run_of_a_source_without_tables_says_so_and_of_a_removed_one_says_that(ready):
    source(ready, "erp", "postgres", 'url = "postgresql://u:p@nowhere.invalid/x"')
    assert ready.run("apply", "sources").returncode == 0
    r = ready.run("run", "erp")
    assert r.returncode == 1 and "no source" not in r.stderr and r.stderr.count("\n") == 1
    assert "erp has no tables;" in r.stderr and "rowvioli list erp" in r.stderr
    (ready.dir / "sources" / "erp.toml").unlink()
    source(ready, "crm", "postgres", 'url = "postgresql://u:p@nowhere.invalid/x"')
    assert ready.run("apply", "sources").returncode == 0
    r = ready.run("run", "erp")
    assert r.returncode == 1 and "erp is not in the definition any more" in r.stderr and r.stderr.count("\n") == 1
    assert "nothing is no source" in ready.run("run", "nothing").stderr


def test_list_of_a_file_source_with_a_missing_directory_names_the_directory(ready):
    source(ready, "files", "file", 'path = "/nowhere/files"')
    r = ready.run("list", "files")
    assert r.returncode == 1 and "/nowhere/files" in r.stderr and "***" not in r.stderr


def test_list_of_a_source_whose_connection_lacks_a_field_names_the_field(ready):
    source(ready, "erp", "postgres", 'host = "x"')
    for cwd in (None, ready.dir / "worker"):
        if cwd:  # the target path: no sources/ here
            assert ready.run("apply", "sources").returncode == 0
            cwd.mkdir()
        r = ready.run("list", "erp", cwd=cwd)
        assert r.returncode == 1 and r.stderr.strip() == "the connection of source erp has no url", r.stderr
