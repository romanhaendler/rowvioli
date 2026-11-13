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
    assert rv.target("select schema_version, max_running from _rowvioli.meta") == [(3, 20)]


def test_init_keeps_what_is_there(rv):
    rv.run("init")
    rv.target("update _rowvioli.meta set max_running = 7")
    rv.target("insert into _rowvioli.sources (name, type) values ('erp', 'postgres')")
    assert rv.run("init").returncode == 0
    assert rv.target("select max_running from _rowvioli.meta") == [(7,)]
    assert rv.target("select name from _rowvioli.sources") == [("erp",)]


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
    assert re.search(r"\b99\b", r.stderr) and re.search(r"\b3\b", r.stderr), r.stderr
    assert rv.target(SHAPE) == shape
    assert rv.target("select count(*) from _rowvioli.sources") == [(0,)]


def test_the_control_connection_asks_postgres_to_notice_a_dead_worker_within_a_minute(rv, monkeypatch):
    # a worker machine that vanishes closes nothing; the server's own keepalive frees its locks (measured: 62 s)
    from rowvioli import target
    monkeypatch.setenv("ROWVIOLI_TARGET_URL", rv.target_url)
    conn = target.connect(init=True)
    names = ["tcp_keepalives_idle", "tcp_keepalives_interval", "tcp_keepalives_count", "tcp_user_timeout"]
    assert [target.sql(conn, f"SELECT current_setting('{n}')")[0][0] for n in names] == ["30", "10", "3", "60000"]
    conn.close()
