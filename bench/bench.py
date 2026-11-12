"""Reproduces the measurement table of the README at 10⁶ rows: `uv run bench/bench.py [rows]`.

One throwaway Postgres container (2 CPUs, 4 GB, as in docs/measurements.md) holds a source database with the
16-column table of the experiments and the target. The program runs as a real process, run by run. Postgres
times its statements (pg_stat_statements), so each step is the server's time for the program's own SQL. Filling
includes reading the source through the postgres connector, because both stream at once.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg

ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
ROWVIOLI = shutil.which("rowvioli", path=os.path.dirname(sys.executable))

SOURCE = """
CREATE TABLE lineitem (id bigint PRIMARY KEY, linenr int, part bigint, supp bigint, qty numeric(12,2),
  price numeric(12,2), disc numeric(4,2), tax numeric(4,2), flag text, status text, ship date, commitd date,
  receipt date, instr text, mode text, comment text);
INSERT INTO lineitem SELECT g, g%%7, g*3, g*5, (g%%50)::numeric, (g%%100000)/100.0, 0.05, 0.08, 'N', 'O',
  date '2020-01-01'+(g%%2000)::int, date '2020-01-01'+(g%%1900)::int, date '2020-01-01'+(g%%2100)::int,
  'DELIVER IN PERSON', 'TRUCK', md5(g::text) FROM generate_series(1, %(n)s) g;
"""

# 1 % updated, 0.1 % deleted, 0.1 % inserted, as in the experiments
CHANGES = """
UPDATE lineitem SET comment = 'changed' WHERE id %% 100 = 0;
DELETE FROM lineitem WHERE id %% 1000 = 1;
INSERT INTO lineitem SELECT g, 1, 1, 1, 1, 1, 0, 0, 'N', 'O', current_date, current_date, current_date, 'x', 'y',
  'new' FROM generate_series(%(n)s + 1, %(n)s + %(n)s / 1000) g;
"""

# the same table twice: with a key, and as a second source without one
DEFINITION = """
[bench]
type    = "postgres"
max_age = "1d"
connection = { url = "%(url)s" }
tables = { lineitem = { key = ["id"] } }

[nokey]
type    = "postgres"
max_age = "1d"
connection = { url = "%(url)s" }
tables = { lineitem = {} }
"""

# the program's statements by step; claim and checks are left out
STEPS = """
SELECT coalesce(sum(total_exec_time) FILTER (WHERE query LIKE 'COPY%FROM STDIN%'), 0) / 1000,
       coalesce(sum(total_exec_time) FILTER (WHERE query LIKE 'CREATE TEMP TABLE _diff%'), 0) / 1000,
       coalesce(sum(total_exec_time) FILTER (WHERE query ~ '^(CREATE TABLE|ALTER TABLE|INSERT INTO|DELETE FROM|COMMIT)'
                                               AND query !~ '_rowvioli'), 0) / 1000
  FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'target')
"""


def query(url, sql, params=None):
    with psycopg.connect(url, autocommit=True) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else None


def main():
    name = f"rowvioli-bench-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, "--label", "rowvioli-test", "--cpus", "2",
                    "--memory", "4g", "--shm-size", "1g", "-e", "POSTGRES_PASSWORD=x", "-p", "127.0.0.1::5432",
                    "postgres:16-alpine", "-c", "shared_preload_libraries=pg_stat_statements"],
                   check=True, capture_output=True)
    try:
        port = subprocess.run(["docker", "port", name, "5432/tcp"], check=True, capture_output=True,
                              text=True).stdout.split()[0].rsplit(":", 1)[1]
        server = f"postgresql://postgres:x@127.0.0.1:{port}"
        for _ in range(120):  # TCP opens only after initdb
            try:
                query(server + "/postgres", "SELECT 1")
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        query(server + "/postgres", "CREATE DATABASE source")
        query(server + "/postgres", "CREATE DATABASE target")
        source, target = server + "/source", server + "/target"
        query(target, "CREATE EXTENSION pg_stat_statements")
        print(f"creating {ROWS:,} rows in the source", file=sys.stderr)
        query(source, SOURCE % {"n": ROWS})
        query(source, "VACUUM ANALYZE lineitem")
        with tempfile.TemporaryDirectory() as dir:
            os.mkdir(f"{dir}/sources")
            with open(f"{dir}/sources/bench.toml", "w") as f:
                f.write(DEFINITION % {"url": source})
            env = {**os.environ, "ROWVIOLI_TARGET_URL": target, "ROWVIOLI_KEY_FILE": f"{dir}/worker.key"}

            def rowvioli(*args):
                p = subprocess.run([ROWVIOLI, *args], cwd=dir, env=env, capture_output=True, text=True)
                if p.returncode:
                    raise SystemExit(f"rowvioli {' '.join(args)} failed: {p.stdout}{p.stderr}")
                return p.stdout

            def run(source_name):
                """One run of lineitem, its steps as Postgres timed them and its seconds as the program says."""
                query(target, "SELECT pg_stat_statements_reset()")
                answer = json.loads(rowvioli("run", source_name, "lineitem", "--slots", "1"))
                [(fill, diff, publish)] = query(target, STEPS)
                return {"fill": fill, "diff": diff, "publish": publish, "run": answer["seconds"]}

            rowvioli("init")
            rowvioli("key", "new")
            rowvioli("apply", "sources/")
            print("running", file=sys.stderr)
            first = run("bench")
            run("nokey")  # its first load
            nokey = run("nokey")
            unchanged = run("bench")
            query(source, CHANGES % {"n": ROWS})
            changed = run("bench")
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)

    s = lambda v: f"{v:.1f} s"
    print(f"| Case | {ROWS:,} rows | whole run |\n|---|---|---|")
    for case, value, whole in [
        ("Comparison when nothing changed", unchanged["diff"], unchanged["run"]),
        ("Computing the diff at 1 % changes", changed["diff"], changed["run"]),
        ("Publishing at 1 % changes", changed["publish"], changed["run"]),
        ("Without a key: replace everything", nokey["publish"], nokey["run"]),
        ("Filling the staging table from the source through ADBC", first["fill"], first["run"]),
        ("Publishing the initial load", first["publish"], first["run"]),
    ]:
        print(f"| {case} | {s(value)} | {s(whole)} |")


if __name__ == "__main__":
    main()
