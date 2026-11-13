"""Measures the history view on a long change log: `uv run bench/history.py [rows] [runs]` (docs/measurements.md, 13).

One throwaway Postgres container (2 CPUs, 4 GB). The program runs as a real process `runs` times; before each
run 1 % of the source rows are updated. Then four queries are timed by EXPLAIN (ANALYZE), without and with an index.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg

ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 300
ROWVIOLI = shutil.which("rowvioli", path=os.path.dirname(sys.executable))

DEFINITION = """
[bench]
type    = "postgres"
max_age = "1d"
connection = { url = "%(url)s" }
tables = { lineitem = { key = ["id"] } }
"""

LOG, VIEW, COLS = "raw_bench.lineitem__log", "raw_bench.lineitem__history", "id, qty, comment"
VIEW_AT = f"SELECT * FROM {VIEW} WHERE _valid_from <= %(m)s AND (_valid_to > %(m)s OR _valid_to IS NULL)"
DIRECT = f"""SELECT * FROM (SELECT DISTINCT ON (id) * FROM {LOG} WHERE _loaded_at <= %(m)s
             ORDER BY id, _loaded_at DESC) l WHERE _op <> 'D'"""


def query(url, sql, params=None):
    with psycopg.connect(url, autocommit=True) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else None


def main():
    name = f"rowvioli-bench-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, "--label", "rowvioli-test", "--cpus", "2",
                    "--memory", "4g", "--shm-size", "1g", "-e", "POSTGRES_PASSWORD=x", "-p", "127.0.0.1::5432",
                    "postgres:16-alpine"], check=True, capture_output=True)
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
        query(source, "CREATE TABLE lineitem (id bigint PRIMARY KEY, qty int, comment text)")
        query(source, "INSERT INTO lineitem SELECT g, 0, md5(g::text) FROM generate_series(1, %s) g", (ROWS,))
        with tempfile.TemporaryDirectory() as dir:
            os.mkdir(f"{dir}/sources")
            with open(f"{dir}/sources/bench.toml", "w") as f:
                f.write(DEFINITION % {"url": source})
            env = {**os.environ, "ROWVIOLI_TARGET_URL": target, "ROWVIOLI_KEY_FILE": f"{dir}/worker.key"}

            def rowvioli(*args):
                p = subprocess.run([ROWVIOLI, *args], cwd=dir, env=env, capture_output=True, text=True)
                if p.returncode:
                    raise SystemExit(f"rowvioli {' '.join(args)} failed: {p.stdout}{p.stderr}")

            rowvioli("init")
            rowvioli("key", "new")
            rowvioli("apply", "sources/")
            for i in range(RUNS):
                if i:
                    query(source, "UPDATE lineitem SET qty = qty + 1, comment = md5(random()::text) "
                                  "WHERE id %% 100 = %s", (i % 100,))
                rowvioli("run", "bench", "lineitem", "--slots", "1")
                if i % 50 == 0:
                    print(f"run {i + 1} of {RUNS}", file=sys.stderr)

        [(m,)] = query(target, f"SELECT DISTINCT _loaded_at FROM {LOG} ORDER BY 1 OFFSET {RUNS // 2} LIMIT 1")
        # the direct query must return what the view's condition returns, before it is timed
        a, b = (f"SELECT {COLS} FROM ({q}) x" for q in (VIEW_AT, DIRECT))
        [(diff, at, n_log, n_view)] = query(
            target, f"""SELECT (SELECT count(*) FROM (({a}) EXCEPT ALL ({b})) x)
                             + (SELECT count(*) FROM (({b}) EXCEPT ALL ({a})) y), (SELECT count(*) FROM ({a}) z),
                               (SELECT count(*) FROM {LOG}), (SELECT count(*) FROM {VIEW})""", {"m": m})
        assert diff == 0 and at > 0, "the direct query differs from the view"
        print(f"log {n_log:,} rows, view {n_view:,} rows, {at:,} rows at the moment {m}", file=sys.stderr)
        cases = [("whole view", f"SELECT * FROM {VIEW}", None), ("view at one moment", VIEW_AT, {"m": m}),
                 ("view for one key", f"SELECT * FROM {VIEW} WHERE id = 5000", None),
                 ("direct query, same moment", DIRECT, {"m": m})]
        for label in ("without an index", "with an index on (id, _loaded_at)"):
            if label.startswith("with an"):
                query(target, f"CREATE INDEX ON {LOG} (id, _loaded_at)")
            query(target, f"ANALYZE {LOG}")
            for case, sql, params in cases:
                times = []
                for _ in range(3):
                    [(plan,)] = query(target, f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", params)
                    times.append(plan[0]["Execution Time"])
                print(f"| {case} | {label} | {sorted(times)[1]:.1f} ms |")
        print(query(target, f"SELECT pg_size_pretty(pg_table_size('{LOG}')), version()"), file=sys.stderr)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)


if __name__ == "__main__":
    main()
