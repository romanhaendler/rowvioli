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
    rows = rv.target("select schema_version, max_running from _rowvioli.meta")
    assert len(rows) == 1
    version, max_running = rows[0]
    assert version is not None and max_running == 20


def test_init_keeps_what_is_there(rv):
    rv.run("init")
    rv.target("update _rowvioli.meta set max_running = 7")
    rv.target("insert into _rowvioli.sources (name, type) values ('erp', 'postgres')")
    assert rv.run("init").returncode == 0
    assert rv.target("select max_running from _rowvioli.meta") == [(7,)]
    assert rv.target("select name from _rowvioli.sources") == [("erp",)]
