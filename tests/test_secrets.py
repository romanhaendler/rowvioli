"""A foreign connector, connection values in its failures, key rotation (spec tests 6, 16, 20)."""
import signal
from types import SimpleNamespace

import pytest
from conftest import until

from test_checks import leaks
from test_run import erp, ok, rows  # noqa: F401 (erp is a fixture)

PASSWORD, TOKEN = "Kenn@wort%42-geheim", "Marke-0815-geheim"


def lab(rv, options="", connection=""):
    """Applies a source of the foreign connector type `testing`, with a password and a token from the environment."""
    rv.definition({"lab.toml": f"""
[lab]
type = "testing"
max_age = "1h"
{options}
[lab.connection]
url = "testing://reader:$LAB_PASSWORD@nowhere/lab"
token = "$LAB_TOKEN"
{connection}
[lab.tables]
"numbers" = {{ key = ["n"] }}
"""})
    r = rv.run("apply", "sources", env={"LAB_PASSWORD": PASSWORD, "LAB_TOKEN": TOKEN})
    assert r.returncode == 0, r.stderr
    return r


def test_a_foreign_connector_installed_through_the_entry_point_loads_a_table(erp):
    lab(erp, "rows = [7, 8]")
    ok(erp, "lab")
    assert rows(erp.target, "select * from raw_lab.numbers") == [(7,), (8,)]


@pytest.mark.parametrize("given, delivered", [('["ab", "cd"]', [("ab",), ("cd",)]), ("[7, 8, 9]", [(7,), (8,), (9,)])])
def test_a_foreign_connector_gets_a_list_named_columns_as_written(erp, given, delivered):
    lab(erp, f"columns = {given}")
    ok(erp, "lab")
    assert rows(erp.target, "select * from raw_lab.numbers") == delivered


@pytest.mark.parametrize("version", ["1.2.3", None])
def test_runs_record_the_version_a_connector_says_its_driver_has_and_none_for_one_that_says_nothing(erp, version):
    lab(erp)
    r = erp.run("run", "lab", env={"ROWVIOLI_TEST_DRIVER_VERSION": version} if version else None)
    assert r.returncode == 0, r.stderr
    assert erp.target("select driver_version from _rowvioli.runs") == [(version,)]


@pytest.mark.parametrize("version", ["1.2\nx", "v" * 201])
def test_a_driver_version_that_is_not_one_short_line_fails_the_run_naming_the_connector(erp, version):
    lab(erp)  # ticket 17, J2: it was stored with every run as given
    erp.target("update _rowvioli.tables set requested_at = now()")
    r = erp.run("run", "lab", env={"ROWVIOLI_TEST_DRIVER_VERSION": version})
    assert r.returncode == 1
    assert erp.target("select reason, driver_version from _rowvioli.runs") == [(
        'connector "testing" says a driver_version that is no text of one line and at most 200 characters, which every '
        'run records: give it a short one, such as "mylib 2.3.1", or none', None)]


@pytest.mark.parametrize("odd, delivered", [("list", "a list, not an Arrow record batch"),
                                            ("schemas", "a batch of another schema than its first")])
def test_a_connector_that_delivers_what_the_contract_does_not_allow_is_named(erp, odd, delivered):
    lab(erp, f'odd = "{odd}"')  # ticket 17, J3: Arrow's own words, `'list' object has no attribute 'schema'`
    assert erp.run("run", "lab").returncode == 1
    assert erp.target("select reason from _rowvioli.runs") == [
        (f'connector "testing" delivered {delivered}, which the contract does not allow',)]


@pytest.mark.parametrize("fail", ["at_once", "deep"])
def test_a_connector_failing_with_connection_values_in_its_message_leaks_none_of_them(erp, fail):
    out = [lab(erp, f'fail = "{fail}"'), erp.run("run", "lab")]
    assert out[-1].returncode == 1
    assert "cannot connect" in erp.target("select reason from _rowvioli.runs")[0][0]
    for value in (PASSWORD, TOKEN, "Kenn%40wort%2542-geheim", "Kenn", "wort%"):
        assert leaks(erp, value, *out) == [], value


@pytest.mark.parametrize("pwd", ["PWD=Odbc-geheim-77", "pwd = {Odbc-geheim-77}"])
def test_the_password_inside_an_odbc_connection_string_leaks_nowhere(erp, pwd):
    out = [lab(erp, 'fail = "at_once"', f'string = "Driver={{X}};UID=reader;{pwd};Encrypt=yes"'), erp.run("run", "lab")]
    assert out[-1].returncode == 1
    assert leaks(erp, "Odbc-geheim-77", *out) == []


def test_a_password_with_quote_backslash_and_newline_does_not_show_in_the_reason_of_a_failed_run(erp):
    odd = "Ge'he\\im\nZeile2-4711"  # written plainly in the definition, so repr shows it in the connector's message
    toml = odd.replace("\\", "\\\\").replace("\n", "\\n")
    erp.definition({"lab.toml": f"""
[lab]
type = "testing"
max_age = "1h"
fail = "at_once"
[lab.connection]
url = "testing://reader:{toml}@nowhere/lab"
token = "Marke-0815-geheim"
[lab.tables]
"numbers" = {{ key = ["n"] }}
"""})
    out = [erp.run("apply", "sources"), erp.run("run", "lab")]
    assert out[-1].returncode == 1
    assert "cannot connect" in erp.target("select reason from _rowvioli.runs")[0][0]
    for value in (odd, repr(odd)[1:-1], "Ge'he", "Zeile2-4711"):
        assert leaks(erp, value, *out) == [], value


def test_a_connector_printing_to_stderr_and_stdout_leaks_nothing_and_disturbs_no_run(erp):
    out = [lab(erp, "print = true"), erp.run("run", "lab")]
    assert out[-1].returncode == 0, out[-1].stdout
    for value in (PASSWORD, TOKEN):
        assert leaks(erp, value, *out) == [], value


def test_key_rotation_with_old_and_new_private_key_in_the_file(erp):
    (erp.dir / "worker.key").rename(erp.dir / "old.key")
    (erp.dir / "worker.pub").rename(erp.dir / "old.pub")
    assert erp.run("key", "new").returncode == 0
    (erp.dir / "both.key").write_text((erp.dir / "old.key").read_text() + (erp.dir / "worker.key").read_text())
    r = erp.run("apply", "sources")  # with the new worker.pub
    assert r.returncode == 0, r.stderr
    r = erp.run("run", env={"ROWVIOLI_KEY_FILE": str(erp.dir / "both.key")})
    assert r.returncode == 0, r.stdout + r.stderr
    erp.target("update _rowvioli.tables set requested_at = now()")
    r = erp.run("run", env={"ROWVIOLI_KEY_FILE": str(erp.dir / "old.key")})
    assert r.returncode == 1
    assert "cannot be decrypted" in erp.target("select reason from _rowvioli.status")[0][0]


def test_the_lines_of_work_leak_no_connection_value(erp):
    lab(erp, 'fail = "deep"')
    worker = erp.start("work")
    until(lambda: erp.target("select count(*) from _rowvioli.status where status = 'failed'") == [(1,)])
    worker.send_signal(signal.SIGTERM)
    out, err = worker.communicate(timeout=20)
    assert "cannot connect" in err
    for value in (PASSWORD, TOKEN, "Kenn%40wort%2542-geheim", "Kenn", "wort%"):
        assert leaks(erp, value, SimpleNamespace(stdout=out, stderr=err)) == [], value


@pytest.mark.parametrize("command", ["status", "run"])
def test_an_error_of_the_target_shows_user_and_host_and_hides_only_the_password(rv, command):
    assert rv.run("key", "new").returncode == 0  # `run` checks the key file before it connects
    url = rv.target_url.replace("postgres:harness-pw-7@", "postgres:zzzz@")
    r = rv.run(command, env={"ROWVIOLI_TARGET_URL": url}, timeout=20)
    assert r.returncode == 1
    assert 'user "postgres"' in r.stderr, r.stderr
