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
