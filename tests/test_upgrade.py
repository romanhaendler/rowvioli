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
    """By table, the reason or the status."""
    return {t.split(".")[1]: r for t, r in rv.target(
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
        r = rv.run("init", env={"ROWVIOLI_TARGET_URL": rv.target_url.replace("postgres:harness-pw-7@", f"{role}:r@")})
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
    assert 'view public.consumer depends on column gone of table raw_erp.viewed' in after["viewed"]
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


@pytest.mark.parametrize("source", ["keeps", "drops"])
def test_a_column_a_person_dropped_from_a_mirror_of_0_4_1_is_closed_in_its_change_log_by_the_first_run_after_init(
        rv, released, source):
    """Ticket 18, review: 0.4.1 left the last value of a column dropped by hand current in the change log, where the
    source dropped it too, and where it kept it and 0.4.1 added it again, for a row whose value had become null."""
    for args in (["init"], ["key", "new"]):
        assert old(rv, released, *args).returncode == 0
    rv.source(SOURCE.strip().split(";\n")[0])
    rv.source(SOURCE.strip().split(";\n")[1])
    definition(rv, {"customers": TABLES["customers"]})
    assert old(rv, released, "apply", "sources").returncode == 0
    assert old(rv, released, "run").returncode == 0
    [(moment,)] = rv.target("select loaded_at from _rowvioli.tables")
    history = at(rv, moment)
    if source == "drops":  # 0.4.1 stops, and its way out is to drop the column from the mirror
        rv.source("alter table customers drop column city")
    rv.target("alter table raw_erp.customers drop column city")
    rv.source("update customers set city = null where id = 1" if source == "keeps" else "select")
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert old(rv, released, "run").returncode == 0
    assert rv.run("init").returncode == 0
    # a consumer's view on the history view, which a change of columns would stop at: closing changes none
    rv.target("create view public.reader as select * from raw_erp.customers__history")
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert rv.run("run").returncode == 0, reasons(rv)
    assert rows(rv.target, "select * from raw_erp.customers") == rows(rv.source, "select * from customers")
    log_replays(rv)
    assert at(rv, moment) == history
    city = "m.city" if source == "keeps" else "null"
    assert rv.target("select count(*) from raw_erp.customers__history h join raw_erp.customers m using (id) "
                     f"where _valid_to is null and h.city is distinct from {city}") == [(0,)]
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert rv.run("run").returncode == 0
    assert rv.target("select count(*) from raw_erp.customers__log where _run = (select max(run) from _rowvioli.runs)") \
        == [(0,)]


# the grants 0.4.1's docs/operation.md "The target" gives a worker's role
OLD_WORKER = """GRANT USAGE ON SCHEMA _rowvioli TO {0};
GRANT SELECT ON _rowvioli.sources, _rowvioli.tables, _rowvioli.meta, _rowvioli.status TO {0};
GRANT UPDATE ON _rowvioli.tables TO {0};
GRANT SELECT, INSERT, UPDATE ON _rowvioli.runs TO {0};
GRANT USAGE ON ALL SEQUENCES IN SCHEMA _rowvioli TO {0};
GRANT CREATE ON DATABASE {1} TO {0}"""


def test_a_worker_role_of_least_rights_loads_under_0_4_1_and_after_init_with_the_grants_it_prints(rv, released):
    """The shakedown's U1 with the worker's role the documents give: it owns the mirrors 0.4.1 made, and after `init`
    by the owner of _rowvioli, and the grants init prints, it takes them on, a table stuck under 0.4.1 included."""
    db = rv.target("select current_database()")[0][0]
    worker = f"worker_{db}"
    env = {"ROWVIOLI_TARGET_URL": rv.target_url.replace("postgres:harness-pw-7@", f"{worker}:w@")}
    for args in (["init"], ["key", "new"]):
        assert old(rv, released, *args).returncode == 0
    for statement in SOURCE.strip().split(";\n")[:4]:  # customers and dropped
        rv.source(statement)
    tables = {"customers": '{ key = ["id"] }', "dropped": '{ key = ["id"] }'}
    definition(rv, tables)
    assert old(rv, released, "apply", "sources").returncode == 0
    rv.target(f"create role {worker} login password 'w'")
    try:
        for statement in OLD_WORKER.format(worker, db).split(";\n"):
            rv.target(statement)
        assert old(rv, released, "run", env=env).returncode == 0
        rv.source("alter table dropped drop column gone; update customers set city = 'Bonn' where id = 1")
        rv.target("update _rowvioli.tables set requested_at = now()")
        assert old(rv, released, "run", env=env).returncode == 1
        assert reasons(rv)["dropped"] == "column gone is missing in the source"
        r = rv.run("init")
        grants = [line for line in r.stdout.splitlines() if line.startswith("GRANT")]
        assert r.returncode == 0 and grants, r.stdout + r.stderr
        rv.target("update _rowvioli.tables set requested_at = now()")
        r = rv.run("run", env=env)  # the worker's role lacks the rights on the new objects
        assert r.returncode == 1 and "rowvioli init printed with the upgrade to version 4" in r.stdout, r.stdout
        for grant in grants:
            rv.target(grant.replace(" TO worker", f" TO {worker}"))
        rv.source("update customers set city = 'Ulm' where id = 2")
        rv.target("update _rowvioli.tables set requested_at = now()")
        r = rv.run("run", env=env)
        assert r.returncode == 0 and set(reasons(rv).values()) == {"ok"}, reasons(rv)
        assert "gone" not in rv.target("select attname from pg_attribute where attrelid = 'raw_erp.dropped'::regclass")
        for t in tables:
            log_replays(rv, f"raw_erp.{t}")
    finally:
        rv.target("drop schema if exists raw_erp cascade")
        rv.target(f"drop owned by {worker} cascade; drop role {worker}")


@pytest.mark.parametrize("hand", ["k2", "k3"])
def test_a_primary_key_changed_by_hand_on_a_mirror_of_0_4_1_stops_and_the_key_it_says_changes_it_as_the_definition_would(
        rv, released, hand):
    """Ticket 19: 0.4.1 wrote the change log under (k), under which k2 was not unique; the definition changes the key
    to (k2), and a person changes the primary key by hand to it, or to a third (k3), before the first run of 0.5."""
    for args in (["init"], ["key", "new"]):
        assert old(rv, released, *args).returncode == 0
    rv.source("create table t (k int primary key, k2 text not null, k3 int not null, v text)")
    rv.source("insert into t values (1, 'a', 10, 'x'), (2, 'a', 20, 'y'), (3, 'c', 40, 'z')")
    definition(rv, {"t": '{ key = ["k"] }'})
    assert old(rv, released, "apply", "sources").returncode == 0
    moments = []
    for change in ("select", "update t set k2 = 'b', k3 = 30 where k = 2"):
        rv.source(change)
        rv.target("update _rowvioli.tables set requested_at = now()")
        assert old(rv, released, "run").returncode == 0
        moments.append((rv.target("select loaded_at from _rowvioli.tables")[0][0],
                        rows(rv.target, "select * from raw_erp.t")))
    assert rv.run("init").returncode == 0
    definition(rv, {"t": '{ key = ["k2"] }'})
    assert rv.run("apply", "sources").returncode == 0
    rv.target(f"alter table raw_erp.t drop constraint t_pkey, add primary key ({hand})")
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert rv.run("run").returncode == 1
    say = ("say the key it was written under, the key the table had when its change log was written, and the next "
           """run changes the key as the definition says: COMMENT ON COLUMN "raw_erp"."t__log"._op IS """
           """'[{"key": ["<the key column>"]}]'""")
    assert reasons(rv)["t"] == (
        "the change log raw_erp.t__log was not written under (k2), the key of the definition and of the mirror's "
        "primary key, so a person changed the primary key by hand before a run changed it: " + say if hand == "k2" else
        "the primary key of raw_erp.t is (k3), the definition's key is (k2), and the change log raw_erp.t__log was "
        "written under neither, so a person changed the primary key by hand before a run changed the key: " + say)
    rv.target(say.split("says: ")[1].replace("<the key column>", "k"))
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert rv.run("run").returncode == 0, reasons(rv)
    moments.append((rv.target("select loaded_at from _rowvioli.tables")[0][0], rows(rv.target, "select * from raw_erp.t")))
    assert rows(rv.target, "select * from raw_erp.t") == rows(rv.source, "select * from t")
    assert rv.target("select a.attname from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = "
                     "any(i.indkey) where i.indrelid = 'raw_erp.t'::regclass and i.indisprimary") == [("k2",)]
    log_replays(rv, "raw_erp.t")
    for moment, mirror in moments:
        assert rows(lambda q: rv.target(q, [moment, moment]), "select k, k2, k3, v from raw_erp.t__history where "
                    "_valid_from <= %s and (_valid_to > %s or _valid_to is null)") == mirror
    rv.target("update _rowvioli.tables set requested_at = now()")
    assert rv.run("run").returncode == 0
    assert rv.target("select count(*) from raw_erp.t__log where _run = (select max(run) from _rowvioli.runs)") == [(0,)]
