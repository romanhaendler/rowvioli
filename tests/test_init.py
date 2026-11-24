import re

import pytest

SHAPE = """
select table_name, column_name, data_type from information_schema.columns
 where table_schema = '_rowvioli' order by 1, 2
"""


def test_init_twice_leaves_the_same_schema_and_meta(rv):
    first = rv.run("init")
    assert first.returncode == 0, first.stderr
    shape = rv.target(SHAPE)
    assert {r[0] for r in shape} == {"sources", "tables", "runs", "meta", "status"}

    second = rv.run("init")
    assert second.returncode == 0, second.stderr
    assert rv.target(SHAPE) == shape
    assert rv.target("select schema_version, max_running from _rowvioli.meta") == [(4, 20)]


def test_init_keeps_what_is_there(rv):
    rv.run("init")
    rv.target("update _rowvioli.meta set max_running = 7")
    rv.target("insert into _rowvioli.sources (name, type) values ('erp', 'postgres')")
    assert rv.run("init").returncode == 0
    assert rv.target("select max_running from _rowvioli.meta") == [(7,)]
    assert rv.target("select name from _rowvioli.sources") == [("erp",)]


def version_3(rv):
    """A target as version 3 left it: without the version columns of runs."""
    rv.target("alter table _rowvioli.runs drop column program_version, drop column driver_version")
    rv.target("update _rowvioli.meta set schema_version = 3")


def test_init_brings_a_version_3_target_to_4_and_changes_nothing_else(rv):
    rv.run("init")
    shape = rv.target(SHAPE)
    rv.target("insert into _rowvioli.sources (name, type) values ('erp', 'postgres')")
    version_3(rv)
    assert rv.target(SHAPE) != shape
    assert rv.run("init").returncode == 0
    assert rv.target(SHAPE) == shape
    assert rv.target("select schema_version from _rowvioli.meta") == [(4,)]
    assert rv.target("select name from _rowvioli.sources") == [("erp",)]


def test_init_refuses_a_target_older_than_version_3_and_leaves_it(rv):  # the steps begin at 3
    rv.run("init")
    version_3(rv)
    rv.target("update _rowvioli.meta set schema_version = 2")
    shape = rv.target(SHAPE)
    r = rv.run("init")
    assert r.returncode != 0
    assert re.search(r"\b2\b", r.stderr) and re.search(r"\b4\b", r.stderr), r.stderr
    assert rv.target(SHAPE) == shape
    assert rv.target("select schema_version from _rowvioli.meta") == [(2,)]


@pytest.mark.parametrize("command", [["init"], ["apply", "sources"], ["run"], ["work"]])
def test_every_command_using_the_target_refuses_another_schema_version_naming_both(rv, command):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    rv.definition({"erp.toml": f'[erp]\ntype = "postgres"\nmax_age = "1h"\n[erp.connection]\n'
                               f'url = "{rv.source_url}"\n[erp.tables]\n"public.t" = {{}}\n'})
    rv.target("update _rowvioli.meta set schema_version = 99")
    shape = rv.target(SHAPE)
    r = rv.run(*command, timeout=20)
    assert r.returncode != 0
    assert re.search(r"\b99\b", r.stderr) and re.search(r"\b4\b", r.stderr), r.stderr
    assert rv.target(SHAPE) == shape
    assert rv.target("select count(*) from _rowvioli.sources") == [(0,)]


@pytest.mark.parametrize("command", [["run"], ["work"]])
def test_a_version_3_target_is_refused_by_every_command_but_init_naming_both_versions(rv, command):
    rv.run("init")
    rv.run("key", "new")
    version_3(rv)
    r = rv.run(*command, timeout=20)
    assert r.returncode != 0
    assert re.search(r"\b3\b", r.stderr) and re.search(r"\b4\b", r.stderr), r.stderr


def test_the_control_connection_asks_postgres_to_notice_a_dead_worker_within_a_minute(rv, monkeypatch):
    # a worker machine that vanishes closes nothing; the server's own keepalive frees its locks (measured: 62 s)
    from rowvioli import target
    monkeypatch.setenv("ROWVIOLI_TARGET_URL", rv.target_url)
    conn = target.connect(init=True)
    names = ["tcp_keepalives_idle", "tcp_keepalives_interval", "tcp_keepalives_count", "tcp_user_timeout"]
    assert [target.sql(conn, f"SELECT current_setting('{n}')")[0][0] for n in names] == ["30", "10", "3", "60000"]
    conn.close()
