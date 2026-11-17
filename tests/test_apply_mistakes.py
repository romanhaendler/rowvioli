"""Mistakes named by `apply`, `init` and `key new` (shakedown ticket 04)."""
import pytest

from test_apply import ENV, ERP, NO_TARGET, check


@pytest.mark.parametrize("old, new, setting", [
    ('max_age = "1h"', 'max_agee = "1h"', "max_age"),
    ('parallel = 4', 'parallel = 4\nlogg = false', "log"),
    ('parallel = 4', 'parallel = 4\ntimzone = "UTC"', "timezone"),
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { targt_table = "n" }', "target_table"),
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { max_agee = "5m" }', "max_age"),
])
def test_a_setting_one_or_two_edits_off_fails_apply_check_and_names_the_setting(rv, old, new, setting):
    r = check(rv, {"erp.toml": ERP.replace(old, new)})
    assert r.returncode != 0
    assert f"did you mean {setting}" in r.stderr


@pytest.mark.parametrize("typo", ['keys = ["id"]', "logs = false", 'max_ages = "5m"'])
def test_a_plural_of_a_setting_is_a_typo(rv, typo):
    r = check(rv, {"erp.toml": ERP.replace('"dbo.Notes"     = {}', f'"dbo.Notes"     = {{ {typo} }}')})
    assert r.returncode != 0 and "did you mean" in r.stderr, r.stderr


def test_a_short_option_is_no_typo(rv):
    r = check(rv, {"erp.toml": ERP.replace('"dbo.Notes"     = {}', '"dbo.Notes"     = { sep = ";" }')})
    assert r.returncode == 0, r.stderr


def test_a_rest_path_without_a_slash_at_the_source_fails_apply(rv):
    text = """
[w]
type = "rest"
max_age = "1h"
path = "items"
[w.connection]
url = "http://127.0.0.1:1"
[w.tables]
a = { columns = { x = "text" } }
"""
    r = check(rv, {"w.toml": text})
    assert r.returncode != 0 and "path must start with /" in r.stderr


def test_a_far_off_option_still_reaches_the_connector(rv):
    r = check(rv, {"erp.toml": ERP.replace('"dbo.Notes"     = {}', '"dbo.Notes"     = { fetch_size = 5 }')})
    assert r.returncode == 0, r.stderr


def test_apply_of_an_empty_directory_fails_and_disables_nothing(rv):
    rv.run("init"), rv.run("key", "new")
    rv.definition({"erp.toml": ERP})
    assert rv.run("apply", "sources", env=ENV).returncode == 0
    (rv.dir / "empty").mkdir()
    r = rv.run("apply", "empty", env=ENV)
    assert r.returncode != 0
    assert "empty" in r.stderr and "every table" in r.stderr
    assert rv.target("select count(*) from _rowvioli.tables where enabled") == [(3,)]
    assert rv.run("apply", "--check", "empty", env=NO_TARGET).returncode != 0


def test_apply_from_the_parent_finds_the_key_next_to_the_directory(rv):
    rv.run("init"), rv.run("key", "new")
    (rv.dir / "def").mkdir()
    (rv.dir / "worker.pub").rename(rv.dir / "def" / "worker.pub")
    (rv.dir / "def" / "sources").mkdir()
    (rv.dir / "def" / "sources" / "erp.toml").write_text(ERP)
    r = rv.run("apply", "def/sources", env=ENV)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("args", [[], ["--init"], ["--key", "nope.pub"]])
def test_a_missing_public_key_names_the_path_tried_and_the_command_that_creates_it(rv, args):
    rv.definition({"erp.toml": ERP})
    r = rv.run("apply", "sources", *args, env=ENV)
    path = "nope.pub" if args[:1] == ["--key"] else str((rv.dir / "worker.pub").resolve())
    assert r.returncode != 0 and path in r.stderr and "rowvioli key new" in r.stderr, r.stderr


def test_key_names_a_key_kept_elsewhere(rv):
    rv.run("init"), rv.run("key", "new")
    rv.definition({"erp.toml": ERP})
    (rv.dir / "worker.pub").rename(rv.dir / "elsewhere.pub")
    r = rv.run("apply", "sources", "--key", "elsewhere.pub", env=ENV)
    assert r.returncode == 0, r.stderr


def test_init_and_key_new_print_one_line_each(rv):
    for args in (["init"], ["key", "new"]):
        r = rv.run(*args)
        assert r.returncode == 0 and len(r.stdout.strip().splitlines()) == 1, r.stdout


def test_a_type_one_or_two_edits_off_a_built_in_connector_fails_apply_check(rv):
    r = check(rv, {"erp.toml": ERP.replace('type = "postgres"', 'type = "postgress"')})
    assert r.returncode != 0 and "did you mean postgres" in r.stderr, r.stderr


@pytest.mark.parametrize("custom", ["sqlite", "weather"])
def test_a_custom_type_passes_apply_check(rv, custom):
    assert check(rv, {"erp.toml": ERP.replace('type = "postgres"', f'type = "{custom}"')}).returncode == 0


def test_apply_without_a_directory_takes_sources(rv):
    rv.definition({"erp.toml": ERP})
    r = rv.run("apply", "--check", env=NO_TARGET)
    assert r.returncode == 0 and "the definition is valid" in r.stdout, r.stderr


@pytest.mark.parametrize("old, new, setting", [
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { max_aeg = "5m" }', "max_age"),  # a swap of neighbours is one edit
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { kye = ["id"] }', "key"),
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { ky = ["id"] }', "key"),
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { kee = ["id"] }', "key"),
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = { lgo = false }', "log"),
])
def test_a_short_or_swapped_setting_fails_apply_check(rv, old, new, setting):
    r = check(rv, {"erp.toml": ERP.replace(old, new)})
    assert r.returncode != 0 and f"did you mean {setting}" in r.stderr, r.stderr


def test_the_connector_options_the_documents_use_are_no_typos(rv):
    options = ('sep = ";", skip = 1, sheet = "a", page = "p", path = "/x", rows = "d", columns = { a = "text" }, '
               'header = true, quote = "x"')
    r = check(rv, {"erp.toml": ERP.replace('"dbo.Notes"     = {}', f'"dbo.Notes"     = {{ {options} }}')})
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("typo, built_in", [("fiel", "file"), ("rset", "rest"), ("postgresql", "postgres"),
                                            ("odbd", "odbc"), ("postgre", "postgres")])
def test_a_type_one_edit_from_a_built_in_name_fails_apply_check_and_says_how_to_pass(rv, typo, built_in):
    r = check(rv, {"erp.toml": ERP.replace('type = "postgres"', f'type = "{typo}"')})
    assert r.returncode != 0 and f"did you mean {built_in}" in r.stderr, r.stderr
    assert "is not a connector" not in r.stderr and "installed" in r.stderr, r.stderr


@pytest.mark.parametrize("passing", ["postgres", "odbc", "postgis", "weather", "testing"])
def test_a_built_in_an_installed_and_a_far_type_pass_apply_check(rv, passing):
    # `testing` is the connector of tests/connector, installed beside the program: an installed type always passes
    assert check(rv, {"erp.toml": ERP.replace('type = "postgres"', f'type = "{passing}"')}).returncode == 0


def test_apply_without_a_directory_and_without_sources_names_where_it_looked(rv):
    r = rv.run("apply", "--check", env=NO_TARGET)
    assert r.returncode != 0 and str((rv.dir / "sources").resolve()) in r.stderr
    assert "rowvioli apply <directory>" in r.stderr


@pytest.mark.parametrize("url", ["postgresql://u:pa@ss@127.0.0.1:1/db", "postgresql://u:p@a@b@127.0.0.1:1/db?x=1"])
def test_a_target_address_with_a_second_at_fails_before_connecting_and_shows_no_part_of_it(rv, url):
    for command in ("init", "status", "run"):
        r = rv.run(command, env={"ROWVIOLI_TARGET_URL": url}, timeout=10)
        assert r.returncode != 0 and "percent-encoded" in r.stderr, r.stderr
        assert "127.0.0.1" not in r.stderr and "u:p" not in r.stderr, r.stderr


def test_a_target_address_with_several_hosts_and_a_query_string_is_no_slip(rv):
    url = "postgresql://postgres:x@127.0.0.1:1,127.0.0.1:2/db?connect_timeout=1&application_name=a"
    r = rv.run("status", env={"ROWVIOLI_TARGET_URL": url}, timeout=20)
    assert "percent-encoded" not in r.stderr
