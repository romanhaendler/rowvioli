"""One run, in a process of its own: claim, read, stage, diff, publish (README "A run", spec "One run").

Prints a JSON line {"claimed": <schema.table>, "run", "max_seconds"} right after the claim and one line
{"table": <schema.table>, "status": ...} at the end, for the worker loop; nothing if it claimed nothing.
"""
import json

from . import connectors, control, seal
from .connectors import quote
from .control import sql

HELD = """SELECT l.classid FROM pg_locks l
           WHERE l.locktype = 'advisory' AND l.objsubid = 2 AND l.granted AND l.classid <> 0
             AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())"""

# The counting lock (0, 0) serialises claims, so the held table locks counted here cannot change meanwhile.
CLAIM = [
    "SELECT pg_advisory_xact_lock(0, 0)",
    f"""SELECT s.id, s.source_id FROM _rowvioli.status s JOIN _rowvioli.sources src ON src.id = s.source_id
         WHERE s.status <> 'loading' AND s.due_at <= now()
           AND ($1::text = '' OR s.source = $1::text) AND ($2::text = '' OR s.source_table = $2::text)
           AND (SELECT count(*) FROM ({HELD}) h WHERE h.classid = s.source_id::oid) < src.parallel
           AND (SELECT count(*) FROM ({HELD}) h) < (SELECT max_running FROM _rowvioli.meta)
         ORDER BY extract(epoch FROM now() - s.due_at) / extract(epoch FROM s.max_age) DESC
         LIMIT 1""",
    "SELECT pg_advisory_lock($1::int, $2::int)",
    "UPDATE _rowvioli.tables SET attempted_at = now(), attempts = attempts + 1, reason = NULL WHERE id = $1",
    """INSERT INTO _rowvioli.runs ("table", worker) VALUES ($1, $2) RETURNING run""",
]

TABLE = """SELECT t.id, s.name, s.type, s.connection, t.source_table, s.target_schema, t.target_table, t.key,
                  t.options::text, s.max_seconds
             FROM _rowvioli.tables t JOIN _rowvioli.sources s ON s.name = t.source WHERE t.id = $1"""


def claim(conn, worker, source, table):
    """Returns the run's facts as a dict, or None if nothing in scope can be claimed."""
    lock, pick, take, attempt, log = CLAIM
    sql(conn, "BEGIN")
    try:
        sql(conn, lock)
        picked = sql(conn, pick, [source, table])
        if not picked:
            sql(conn, "ROLLBACK")
            return None
        id, source_id = picked[0]
        sql(conn, take, [source_id, id])
        sql(conn, attempt, [id])
        [(run,)] = sql(conn, log, [id, worker])
        sql(conn, "COMMIT")
    except Exception:
        sql(conn, "ROLLBACK")
        raise
    keys = ("id", "source", "type", "connection", "source_table", "schema", "table", "key", "options", "max_seconds")
    t = dict(zip(keys, sql(conn, TABLE, [id])[0]), run=run, worker=worker)
    t["mirror"] = f"{quote(t['schema'])}.{quote(t['table'])}"
    t["log"] = f"{quote(t['schema'])}.{quote(t['table'] + '__log')}"
    return t


def stage(conn, t):
    """Steps 2-3: open the connection, call the connector, fill the TEMP staging table. Returns rows read."""
    connection = seal.open_(seal.load_private(), t["source"], t["connection"])
    batches = connectors.REGISTRY[t["type"]](connection, t["source_table"], json.loads(t["options"]))
    with conn.cursor() as c:
        return c.adbc_ingest("_stage", batches, mode="create", temporary=True)


def diff(conn, t, cols, new):
    """Step 5: the differences into the TEMP table _diff (README "Comparing in the target"). Returns counts."""
    s = ", ".join("s." + c for c in cols)
    m = ", ".join("m." + c for c in cols)
    on = " AND ".join(f"s.{quote(k)} = m.{quote(k)}" for k in t["key"])
    if new:
        sql(conn, f"CREATE TEMP TABLE _diff AS SELECT 'I'::text AS _op, {s} FROM _stage s")
    else:
        sql(conn, f"""CREATE TEMP TABLE _diff AS
            SELECT 'D'::text AS _op, {m} FROM {t['mirror']} m WHERE NOT EXISTS (SELECT 1 FROM _stage s WHERE {on})
            UNION ALL
            SELECT CASE WHEN m.{quote(t['key'][0])} IS NULL THEN 'I' ELSE 'U' END, {s}
              FROM _stage s LEFT JOIN {t['mirror']} m ON {on}
             WHERE m.{quote(t['key'][0])} IS NULL OR ROW({s}) IS DISTINCT FROM ROW({m})""")
    counts = dict(sql(conn, "SELECT _op, count(*) FROM _diff GROUP BY _op"))
    return {"inserted": counts.get("I", 0), "updated": counts.get("U", 0), "deleted": counts.get("D", 0)}


def publish(conn, t, rows_read):
    """Steps 4-6. Checks (ticket 04) go between staging and diff."""
    cols = [quote(c) for (c,) in sql(conn, """SELECT attname FROM pg_attribute WHERE attrelid = 'pg_temp._stage'::regclass
                                                AND attnum > 0 AND NOT attisdropped ORDER BY attnum""")]
    names = ", ".join(cols)
    new = sql(conn, "SELECT to_regclass($1) IS NULL", [t["mirror"]])[0][0]
    counts = diff(conn, t, cols, new) if t["key"] else None
    if new:
        # Two first runs of one source race on IF NOT EXISTS (unique violation). Waiting for a lock inside a
        # transaction block does not refresh the catalog cache, so the schema is created in its own transaction.
        sql(conn, "SELECT pg_advisory_lock(hashtext($1))", [t["schema"]])  # one-key lock, never a table lock
        sql(conn, f"CREATE SCHEMA IF NOT EXISTS {quote(t['schema'])}")
        sql(conn, "SELECT pg_advisory_unlock(hashtext($1))", [t["schema"]])
    sql(conn, "BEGIN")
    if new:  # the first run creates the mirror inside publishing, so it never exists empty
        pk = f", PRIMARY KEY ({', '.join(quote(k) for k in t['key'])})" if t["key"] else ""
        sql(conn, f"CREATE TABLE {t['mirror']} (LIKE _stage{pk})")
        if t["key"]:
            sql(conn, f"CREATE TABLE {t['log']} (_run bigint, _op text, LIKE {t['mirror']})")
    if t["key"]:
        on = " AND ".join(f"d.{quote(k)} = m.{quote(k)}" for k in t["key"])
        sql(conn, f"INSERT INTO {t['log']} SELECT $1, _op, {names} FROM _diff", [t["run"]])
        sql(conn, f"DELETE FROM {t['mirror']} m USING _diff d WHERE d._op IN ('D', 'U') AND {on}")
        sql(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _diff WHERE _op IN ('I', 'U')")
    else:  # without a key: replaced as a whole, no change log
        deleted = rowcount(conn, f"DELETE FROM {t['mirror']}")
        counts = {"inserted": rowcount(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _stage"),
                  "updated": 0, "deleted": deleted}
    sql(conn, "UPDATE _rowvioli.tables SET loaded_at = now(), attempts = 0 WHERE id = $1", [t["id"]])
    sql(conn, """UPDATE _rowvioli.runs SET status = 'ok', finished_at = clock_timestamp(), rows_read = $2,
                        inserted = $3, updated = $4, deleted = $5 WHERE run = $1""",
        [t["run"], rows_read, counts["inserted"], counts["updated"], counts["deleted"]])
    sql(conn, "COMMIT")
    return {"status": "ok", **counts}


def rowcount(conn, query):
    with conn.cursor() as c:
        c.execute(query)
        return c.rowcount


def fail(conn, t, reason):
    """The one failure path of a run: status first, then the lock (released when the connection closes)."""
    sql(conn, "ROLLBACK")  # outside a transaction this is only a warning
    sql(conn, "UPDATE _rowvioli.tables SET reason = $2 WHERE id = $1", [t["id"], reason])
    sql(conn, """UPDATE _rowvioli.runs SET status = 'failed', finished_at = clock_timestamp(), reason = $2
                  WHERE run = $1""", [t["run"], reason])
    return {"status": "failed", "reason": reason}


def load(worker, source="", table=""):
    with control.connect() as conn:
        t = claim(conn, worker, source, table)
        if t is None:
            return
        name = f"{t['schema']}.{t['table']}"
        # tells the worker what to end after max_seconds
        print(json.dumps({"claimed": name, "run": t["run"], "max_seconds": t["max_seconds"]}), flush=True)
        try:
            answer = publish(conn, t, stage(conn, t))
        except Exception as e:
            answer = fail(conn, t, str(e))
        print(json.dumps({"table": name, **answer}), flush=True)
