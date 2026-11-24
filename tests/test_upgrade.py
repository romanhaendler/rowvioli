"""The upgrade from the released 0.4.1 itself (decision 54; the shakedown's U1): its source from the tag v0.4.1, run
with this environment's Python and libraries, builds a target with tables that load and tables stuck on each reason
it stops with; then `init` of this program, and every table loads or stops with its way out, the history before the
upgrade stays what it was, and old and new program refuse each other's target."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROWVIOLI
from test_columns_go_and_come import log_replays
from test_init import SHAPE
from test_run import rows

REPO = Path(__file__).resolve().parent.parent
HOW = "needs the tag v0.4.1 in the repository: git fetch --tags"


@pytest.fixture(scope="session")
def released(tmp_path_factory):
    """The source of 0.4.1 from its tag, no network needed: its dependencies are this program's."""
    where = tmp_path_factory.mktemp("v0.4.1")
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "v0.4.1", "src"], capture_output=True)
    if archive.returncode:
        pytest.skip(HOW)
    subprocess.run(["tar", "-x", "-C", str(where)], input=archive.stdout, check=True)
    return where / "src"


def old(rv, released, *args, env=None):
    """`rowvioli` of 0.4.1: its package first on the path, also for the run processes its worker starts."""
    return subprocess.run([sys.executable, "-m", "rowvioli", *args], cwd=rv.dir, capture_output=True, text=True,
                          timeout=60, env=rv._env({"PYTHONPATH": str(released), **(env or {})}))


SOURCE = """
create table customers (id int primary key, name text, city text);
insert into customers select g, 'n' || g, 'c' || g from generate_series(1, 10) g;
create table dropped (id int primary key, v text, gone text);
insert into dropped select g, 'v' || g, 'g' || g from generate_series(1, 10) g;
create table viewed (id int primary key, gone text);
insert into viewed select g, 'g' || g from generate_series(1, 10) g;
create table retyped (id int primary key, v int);
insert into retyped select g, g from generate_series(1, 10) g;
create table amounts (id int primary key, amt numeric(8,2));
insert into amounts select g, g * 1.11 from generate_series(1, 10) g;
create table pkhand (id int primary key, v text);
insert into pkhand select g, 'v' || g from generate_series(1, 10) g;
create table keyed (id int primary key, id2 int not null, v text);
insert into keyed select g, g + 100, 'v' || g from generate_series(1, 10) g;
create table own (id int primary key, v text);
insert into own select g, 'v' || g from generate_series(1, 10) g;
create table nokey (a int, b text);
insert into nokey select g, 'b' || g from generate_series(1, 10) g;
create table nolog (id int primary key, v text);
insert into nolog select g, 'v' || g from generate_series(1, 10) g"""

TABLES = {"customers": '{ key = ["id"] }', "dropped": '{ key = ["id"] }', "viewed": '{ key = ["id"] }',
          "retyped": '{ key = ["id"] }', "amounts": '{ key = ["id"] }', "pkhand": '{ key = ["id"] }',
          "keyed": '{ key = ["id"] }', "own": '{ key = ["id"] }', "nokey": "{}",
          "nolog": '{ key = ["id"], log = false }'}


def definition(rv, tables):
    rv.definition({"erp.toml": f'[erp]\ntype = "postgres"\nmax_age = "1h"\n[erp.connection]\nurl = '
                               f'"{rv.source_url}"\n[erp.tables]\n'
                   + "".join(f'"public.{t}" = {o}\n' for t, o in tables.items())})


def at(rv, moment):
    return rows(lambda q: rv.target(q, [moment, moment]), "select id, name, city from raw_erp.customers__history "
                "where _valid_from <= %s and (_valid_to > %s or _valid_to is null)")


def reasons(rv):
    """By table, the source's password x put back where the reason hides it."""
    return {t.split(".")[1]: r.replace("***", "x") for t, r in rv.target(
        "select target_table, coalesce(reason, status) from _rowvioli.status")}


# what the catalogue says of the schema _rowvioli: its columns, indexes and constraints
CATALOGUE = SHAPE, """select indexdef from pg_indexes where schemaname = '_rowvioli' order by 1""", """
    select conrelid::regclass::text, pg_get_constraintdef(oid) from pg_constraint
     where connamespace = '_rowvioli'::regnamespace order by 1, 2"""


def test_a_target_of_the_released_0_4_1_with_every_stuck_state_is_upgraded_by_init_and_every_table_goes_on(
        rv, released):
    for args in (["init"], ["key", "new"]):
        assert old(rv, released, *args).returncode == 0
    for statement in SOURCE.strip().split(";\n"):
        rv.source(statement)
    definition(rv, TABLES)
    assert old(rv, released, "apply", "sources").returncode == 0
    assert old(rv, released, "run").returncode == 0, "the first loads of 0.4.1"
    rv.source("update customers set city = 'Bonn' where id = 1; update pkhand set v = 'w' where id = 1")
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert old(rv, released, "run").returncode == 0
    [(moment,)] = rv.target("select loaded_at from _rowvioli.tables where target_table = 'customers'")
    before = {t: rows(rv.target, f"select * from raw_erp.{t}") for t in ("customers", "pkhand")}
    history = at(rv, moment)
    # every reason 0.4.1 stops with
    rv.target("create view public.consumer as select gone from raw_erp.viewed")
    rv.target("alter table raw_erp.pkhand drop constraint pkhand_pkey, add primary key (id, v)")
    rv.target("alter table raw_erp.own add column mine text default 'kept'")
    for statement in ["alter table dropped drop column gone", "alter table viewed drop column gone",
                      "alter table retyped alter v type text using v || 'x'",
                      "alter table amounts alter amt type numeric(14,2)", "update amounts set amt = 1234567890.12",
                      "alter table nokey drop column b", "alter table nolog drop column v"]:
        rv.source(statement)
    definition(rv, {**TABLES, "keyed": '{ key = ["id2"] }'})
    assert old(rv, released, "apply", "sources").returncode == 0
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert old(rv, released, "run").returncode == 1
    stuck = reasons(rv)
    assert stuck == {
        "customers": "ok", "dropped": "column gone is missing in the source", "viewed": "column gone is missing in "
        "the source", "retyped": "column v has changed its type from integer to text", "amounts": stuck["amounts"],
        "pkhand": stuck["pkhand"], "keyed": stuck["keyed"], "own": "column mine is missing in the source",
        "nokey": "column b is missing in the source", "nolog": "column v is missing in the source"}, stuck
    assert "amt" in stuck["amounts"] and "differs from the mirror's primary key" in stuck["pkhand"] + stuck["keyed"]

    # the new program refuses the old target, and the old program the new one
    r = rv.run("run")
    assert r.returncode == 1 and "this program works with version 4; rowvioli init brings it to 4" in r.stderr
    catalogue = [rv.target(q) for q in CATALOGUE]
    role = f"reader_{rv.target_url.rsplit('/', 1)[1]}"
    rv.target(f"create role {role} login password 'r'")
    try:  # init as a role without rights changes nothing
        r = rv.run("init", env={"ROWVIOLI_TARGET_URL": rv.target_url.replace("postgres:x@", f"{role}:r@")})
        assert r.returncode == 1 and [rv.target(q) for q in CATALOGUE] == catalogue
    finally:
        rv.target(f"drop role {role}")
    r = rv.run("init")
    assert r.returncode == 0 and "GRANT" in r.stdout, r.stdout + r.stderr
    # the same schema as a target the new program begins: init it in the source's database
    assert rv.run("init", env={"ROWVIOLI_TARGET_URL": rv.source_url}).returncode == 0
    assert [rv.source(q) for q in CATALOGUE] == [rv.target(q) for q in CATALOGUE]
    r = old(rv, released, "run")
    assert r.returncode == 1 and "4" in r.stderr and "3" in r.stderr, r.stderr

    rv.target("update _rowvioli.tables set requested_at = now()")
    assert subprocess.run([ROWVIOLI, "run"], cwd=rv.dir, env=rv._env(None), capture_output=True,
                          text=True).returncode == 1  # viewed, own, nokey and nolog stop, each with its way out
    after = reasons(rv)
    assert {t for t, r in after.items() if r == "ok"} == {"customers", "dropped", "retyped", "amounts", "pkhand"}, \
        after
    # 0.4.1 hashed the whole definition and its change log has first rows only: either key could have written it
    assert after["keyed"].startswith("the primary key of raw_erp.keyed is (id), the definition's key is (id2), and "
                                     "nothing in the target tells"), after["keyed"]
    assert 'view consumer depends on column gone of table raw_erp.viewed' in after["viewed"]
    assert after["own"].startswith("column mine of the mirror is not in the change log")
    for t, c in (("nokey", "b"), ("nolog", "v")):
        assert after[t].endswith(f'ALTER TABLE "raw_erp"."{t}" DROP COLUMN "{c}"'), after[t]
    # the history before the upgrade is what it was; a primary key changed by hand is put back
    assert at(rv, moment) == history == before["customers"]
    assert rows(rv.target, "select * from raw_erp.pkhand") == before["pkhand"]
    assert rv.target("""select "by" from _rowvioli.columns where target_table = 'pkhand' and "column" = 'id'""") == [
        ("hand",)]
    assert rv.target("select count(*) from raw_erp.pkhand__log where _op = 'D'") == [(0,)]
    assert rv.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'amt' and attrelid = "
                     "'raw_erp.amounts'::regclass") == [("numeric(14,2)",)]
    for t in ("customers", "dropped", "retyped", "amounts", "pkhand"):
        log_replays(rv, f"raw_erp.{t}")
    # each way out leads out
    rv.target("drop view public.consumer")
    rv.target("alter table raw_erp.own drop column mine")
    rv.target('alter table raw_erp.nokey drop column b; alter table raw_erp.nolog drop column v')
    rv.target(re.search(r", or (COMMENT .*) where the definition changed the key$", after["keyed"])[1])
    rv.target("update _rowvioli.tables set requested_at = now()")
    r = rv.run("run")
    assert r.returncode == 0, reasons(rv)
    assert rv.target("select _op, count(*) from raw_erp.keyed__log where _run = (select max(_run) from "
                     "raw_erp.keyed__log) group by 1 order by 1") == [("D", 10), ("I", 10)]
    for t in ("keyed", "viewed", "own"):
        log_replays(rv, f"raw_erp.{t}")
