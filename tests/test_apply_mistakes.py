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


def test_a_missing_default_key_names_the_path_tried(rv):
    rv.run("init")
    rv.definition({"erp.toml": ERP})
    r = rv.run("apply", "sources", env=ENV)
    assert r.returncode != 0
    assert str((rv.dir / "worker.pub").resolve()) in r.stderr


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
