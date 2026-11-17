# Question: can ADBC alone carry the control connection (lock, TEMP staging, diff, transaction
# on ONE connection)? Compared with psycopg 3, once row by row, once with pgpq (Arrow -> binary COPY).
#
#   docker run -d --name rowvioli-exp8 -e POSTGRES_PASSWORD=x -p 54408:5432 postgres:16-alpine
#   uv run --with adbc-driver-postgresql --with pyarrow --with "psycopg[binary]" --with pgpq python 08_drivers.py
import datetime as dt, decimal, sys, time
from importlib.metadata import version
import pyarrow as pa
import adbc_driver_postgresql.dbapi as adbc
import psycopg

URL = "postgresql://postgres:x@localhost:54408/postgres?keepalives_idle=30&keepalives_interval=10&keepalives_count=3"
N, CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000, 10_000
SCHEMA = pa.schema([("id", pa.int64()), ("name", pa.string()), ("amount", pa.decimal128(12, 2)),
                    ("ts", pa.timestamp("us", tz="UTC")), ("day", pa.date32()), ("active", pa.bool_()),
                    ("value", pa.float64()), ("empty", pa.string())])
COLS = ", ".join(SCHEMA.names)
PG = {"int64": "bigint", "string": "text", "decimal128(12, 2)": "numeric(12,2)", "timestamp[us, tz=UTC]": "timestamptz",
      "date32[day]": "date", "bool": "boolean", "double": "double precision"}   # psycopg needs its own type table
DDL = ", ".join(f"{f.name} {PG[str(f.type)]}" for f in SCHEMA)
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)

def batch(start, n, gen):   # gen > 0: every 100th row has a different name
    ids = list(range(start, min(start + CHUNK, n)))
    return pa.record_batch([
        ids, [f"customer {i}" + (f" v{gen}" if gen and i % 100 == 0 else "") for i in ids],
        [decimal.Decimal(i % 100000) / 100 for i in ids], [T0 + dt.timedelta(seconds=i) for i in ids],
        [T0.date() + dt.timedelta(days=i % 365) for i in ids], [i % 2 == 0 for i in ids],
        [i / 7 for i in ids], [None] * len(ids)], schema=SCHEMA)

DATA = {g: [batch(s, N, g) for s in range(0, N, CHUNK)] for g in (0, 1)}   # generated upfront, not part of the time

obs = psycopg.connect(URL, autocommit=True)   # observer: second connection, sees only what is published
def see(sql): return obs.execute(sql).fetchone()[0]
def locks(key): return see(f"select count(*) from pg_locks where locktype='advisory' and classid=1 and objid={key}")
def check(label, ok, extra=""): print(f"  {'ok  ' if ok else 'NO  '} {label} {extra}")

def diff_sql(t):
    return f"""CREATE TEMP TABLE diff AS
      SELECT 'D'::text AS _op, {COLS} FROM {t} m WHERE NOT EXISTS (SELECT 1 FROM stage s WHERE s.id = m.id)
      UNION ALL
      SELECT CASE WHEN m.id IS NULL THEN 'I' ELSE 'U' END, {', '.join('s.' + c for c in SCHEMA.names)}
      FROM stage s LEFT JOIN {t} m ON m.id = s.id
      WHERE m.id IS NULL OR ROW({', '.join('s.' + c for c in SCHEMA.names)}) IS DISTINCT FROM ROW({', '.join('m.' + c for c in SCHEMA.names)})"""

def setup(t):
    obs.execute(f"create schema if not exists raw; drop table if exists {t}; create table {t} ({DDL}, primary key (id))")
    obs.execute("create table if not exists runs (run int primary key, status text, inserted bigint)")
    obs.execute("delete from runs; insert into runs values (1,'running',null),(2,'running',null)")

def one_run(name, key, t, sql, one, fill, begin, commit, rollback, close, errtype):
    """One run, independent of the driver. sql/one/fill/... are the five things the driver must be able to do."""
    print(f"\n== {name}")
    setup(t)
    check("session lock taken", one(f"select pg_try_advisory_lock(1, {key})") is True and locks(key) == 1)
    sql("set lock_timeout = '5s'"); sql("set client_connection_check_interval = '2s'")
    check("session settings set", one("select current_setting('lock_timeout')") == "5s")
    for run, gen in ((1, 0), (2, 1)):
        sql("drop table if exists stage"); sql("drop table if exists diff")
        t1 = time.time(); fill(DATA[gen]); t_fill = time.time() - t1
        if run == 1:
            types = one("select string_agg(format_type(atttypid, atttypmod), ', ' order by attnum) from pg_attribute where attrelid='stage'::regclass and attnum>0")
            print(f"       Types in staging: {types}")
            check("staging is TEMP and visible only here", see("select count(*) from pg_class where relname='stage' and relpersistence<>'t'") == 0
                  and one("select relpersistence::text from pg_class where relname='stage'") == "t")
        t1 = time.time(); sql(diff_sql(t)); t_diff = time.time() - t1
        ops = one("select coalesce(string_agg(_op || '=' || n, ' ' order by _op), 'empty') from (select _op, count(*) n from diff group by 1) x")
        before = see(f"select count(*) from {t}")
        t1 = time.time(); begin()
        sql(f"DELETE FROM {t} m USING diff d WHERE d._op IN ('D','U') AND d.id = m.id")
        sql(f"INSERT INTO {t} SELECT {COLS} FROM diff WHERE _op IN ('I','U')")
        sql("UPDATE runs SET status = 'ok', inserted = $1 WHERE run = $2", (N, run))
        invisible = see(f"select count(*) from {t}") == before and see(f"select status from runs where run={run}") == "running"
        commit(); t_pub = time.time() - t1
        print(f"       Run {run}: fill {t_fill:.1f} s, diff {t_diff:.1f} s, publish {t_pub:.1f} s, diff: {ops}")
        check(f"Run {run}: invisible before COMMIT, visible after",
              invisible and see(f"select count(*) from {t}") == N and see(f"select status from runs where run={run}") == "ok")
    check("lock still held after COMMIT", locks(key) == 1)
    begin(); sql(f"DELETE FROM {t}"); rollback()
    check("ROLLBACK leaves the mirror unchanged, the lock stays", see(f"select count(*) from {t}") == N and locks(key) == 1)
    begin()
    try: sql(f"INSERT INTO {t} (id) VALUES (0)"); err = None
    except errtype as e: err = e
    rollback()
    check("SQL error with SQLSTATE 23505", getattr(err, "sqlstate", None) == "23505", f"({type(err).__name__})")
    check("afterwards: connection, lock and staging still there", one("select count(*) from stage") == N and locks(key) == 1)
    close(); time.sleep(0.3)
    check("after close: lock gone", locks(key) == 0)

# ---------- ADBC alone
print("adbc", version("adbc-driver-postgresql"), "| pyarrow", pa.__version__, "| psycopg", psycopg.__version__, "| rows", N)
a = adbc.connect(URL, autocommit=True)
def a_sql(q, p=None):
    with a.cursor() as c: c.execute(q, p)
def a_one(q):
    with a.cursor() as c: c.execute(q); return c.fetchone()[0]
stream = {}
def a_fill(batches):
    def gen():
        for i, b in enumerate(batches):
            if i == len(batches) // 2:   # in the middle of reading: has anything reached the server yet?
                stream["middle"] = see("select coalesce(max(tuples_processed), 0) from pg_stat_progress_copy")
            yield b
    with a.cursor() as c: c.adbc_ingest("stage", pa.RecordBatchReader.from_batches(SCHEMA, gen()), mode="create", temporary=True)
one_run("ADBC alone", 81, "raw.customers_adbc", a_sql, a_one, a_fill,
     lambda: a_sql("BEGIN"), lambda: a_sql("COMMIT"), lambda: a_sql("ROLLBACK"), a.close, adbc.Error)
check("ingest streams (the server has rows before the reader is done)", stream.get("middle", 0) > 0, f"({stream.get('middle')} rows at half time)")

# ---------- psycopg 3, variants for filling
p = psycopg.connect(URL, autocommit=True)
tx = []
def p_sql(q, p_=None): p.execute(q, p_)
def p_one(q): return p.execute(q).fetchone()[0]
def p_begin(): tx.append(p.transaction()); tx[-1].__enter__()
def p_commit(): tx.pop().__exit__(None, None, None)
def p_rollback(): tx.pop().__exit__(psycopg.Rollback, psycopg.Rollback(), None)
def p_fill_rows(batches):
    p.execute(f"create temp table stage ({DDL})")
    with p.cursor().copy(f"COPY stage ({COLS}) FROM STDIN") as cp:
        for b in batches:
            for row in zip(*(col.to_pylist() for col in b.columns)): cp.write_row(row)
def p_fill_pgpq(batches):
    import pgpq
    enc = pgpq.ArrowToPostgresBinaryEncoder(SCHEMA)
    p.execute(f"create temp table stage ({DDL})")
    with p.cursor().copy(f"COPY stage ({COLS}) FROM STDIN WITH (FORMAT BINARY)") as cp:
        cp.write(enc.write_header())
        for b in batches: cp.write(enc.write_batch(b))
        cp.write(enc.finish())

fix = lambda q: q.replace("$1", "%s").replace("$2", "%s")
one_run("psycopg 3, row by row", 82, "raw.customers_psy", lambda q, p_=None: p_sql(fix(q), p_), p_one, p_fill_rows,
     p_begin, p_commit, p_rollback, p.close, psycopg.Error)
try:
    p = psycopg.connect(URL, autocommit=True)
    one_run("psycopg 3 + pgpq", 83, "raw.customers_pgpq", lambda q, p_=None: p_sql(fix(q), p_), p_one, p_fill_pgpq,
         p_begin, p_commit, p_rollback, p.close, psycopg.Error)
except Exception as e:
    print(f"  NO   psycopg + pgpq: {type(e).__name__}: {str(e)[:200]}")
