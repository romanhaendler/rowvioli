"""One run, in a process of its own (README "A run"): claim, stage, diff, publish, or fail.

Started by the worker loop as `python -m rowvioli.load <worker> <source> <table>`. It tells the worker on stdout,
one JSON object per line: {"claimed": <target table>, "run", "max_seconds"} right after the claim, before reading,
and {"table": <target table>, "status", ...counts or "reason"} at the end. It prints nothing if it claimed nothing.
"""
import itertools
import json
import os
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

import pyarrow as pa

from . import contract, seal, target
from .target import CLAIMABLE, quote, sql

TABLE = """SELECT t.id, s.name, s.type, s.connection, s.key_id, t.source_table, s.target_schema, t.target_table,
                  t.key, t.log, t.max_seconds, (s.options || t.options)::text, t.max_delete_share::float8
             FROM _rowvioli.tables t JOIN _rowvioli.sources s ON s.name = t.source WHERE t.id = $1"""

# the columns of a table by name and type as Postgres shows them; none for a table that does not exist
COLUMNS = """SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute
              WHERE attrelid = to_regclass($1) AND attnum > 0 AND NOT attisdropped ORDER BY attnum"""

PRIMARY_KEY = """SELECT a.attname FROM pg_index i, unnest(i.indkey) WITH ORDINALITY k(attnum, n), pg_attribute a
                  WHERE i.indrelid = $1::regclass AND i.indisprimary AND a.attrelid = i.indrelid
                    AND a.attnum = k.attnum ORDER BY k.n"""


def claim(conn, worker, source, table):
    """In one transaction under the counting lock (README "How Postgres counts"): takes the table lock of the
    most overdue claimable table in scope, counts the attempt and opens the run's row with the hash of the
    definition. Returns the run's facts, as the definition says at this moment, or None."""
    sql(conn, "BEGIN")
    try:
        sql(conn, "SELECT pg_advisory_xact_lock(0, 0)")
        picked = sql(conn, f"SELECT id, source_id FROM ({CLAIMABLE}) c ORDER BY overdue DESC LIMIT 1",
                     [source, table])
        if not picked:
            sql(conn, "ROLLBACK")
            return None
        id, source_id = picked[0]
        sql(conn, "SELECT pg_advisory_lock($1::int, $2::int)", [source_id, id])  # the table lock outlives COMMIT
        sql(conn, "UPDATE _rowvioli.tables SET attempted_at = now(), attempts = attempts + 1, reason = NULL"
                  " WHERE id = $1", [id])
        [(run,)] = sql(conn, """INSERT INTO _rowvioli.runs ("table", worker, definition)
                                SELECT $1, $2, definition FROM _rowvioli.meta RETURNING run""", [id, worker])
        facts = sql(conn, TABLE, [id])[0]
        sql(conn, "COMMIT")
    except BaseException:
        sql(conn, "ROLLBACK")
        raise
    keys = ("id", "source", "type", "connection", "key_id", "source_table", "schema", "table", "key", "log",
            "max_seconds", "options", "max_delete_share")
    t = dict(zip(keys, facts), run=run, worker=worker)
    t["options"] = json.loads(t["options"])  # the source's options, overridden by the table's
    t["name"] = f"{t['schema']}.{t['table']}"
    t["mirror"] = f"{quote(t['schema'])}.{quote(t['table'])}"
    t["log_table"] = f"{quote(t['schema'])}.{quote(t['table'] + '__log')}"
    return t


def load(conn, t):
    """Steps 2 to 6. Raises with the reason when the run fails."""
    rows_read = stage(conn, t)
    if rows_read == 0:
        raise Exception("the source delivered zero rows")
    staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    mirror = sql(conn, COLUMNS, [t["mirror"]])  # empty before the first run
    check(conn, t, staged, mirror)
    counts = diff(conn, t, staged, mirror) if t["key"] else None
    if mirror:
        limit(conn, t, rows_read, counts)
    return publish(conn, t, staged, mirror, rows_read, counts)


def check(conn, t, staged, mirror):
    """Step 4 (README "Checks before publishing"). A new column passes, publish adds it (decision 17)."""
    types = dict(staged)
    for name, type in mirror:
        if name not in types:
            raise Exception(f"column {name} is missing in the source")
        if types[name] != type:
            raise Exception(f"column {name} has changed its type from {type} to {types[name]}")
    key = t["key"] or []
    if mirror:
        primary_key = [k for (k,) in sql(conn, PRIMARY_KEY, [t["mirror"]])]
        if primary_key != key:
            raise Exception(f"the key {key} differs from the mirror's primary key {primary_key}")
    if key:
        names = ", ".join(quote(k) for k in key)
        if sql(conn, f"SELECT 1 FROM _stage WHERE {' OR '.join(quote(k) + ' IS NULL' for k in key)} LIMIT 1"):
            raise Exception(f"a key column of ({names}) is null")
        if sql(conn, f"SELECT 1 FROM _stage GROUP BY {names} HAVING count(*) > 1 LIMIT 1"):
            raise Exception(f"a key combination of ({names}) occurs twice")


def limit(conn, t, rows_read, counts):
    """After step 5: a broken source must not empty the mirror in a perfectly consistent way (decision 18).
    Without a key the shrinkage counts."""
    before = sql(conn, f"SELECT count(*) FROM {t['mirror']}")[0][0]
    gone = counts["deleted"] if counts else before - rows_read
    if before and gone / before > t["max_delete_share"]:
        raise Exception(f"{round(100 * gone / before)} % of the rows would be deleted")


def stage(conn, t):
    """Opens the connection, calls the connector and fills the TEMP staging table chunk by chunk. Returns the
    number of rows read."""
    connector = contract.connector(t["type"])
    if connector is None:
        raise Exception(f'connector "{t["type"]}" is not installed on worker {t["worker"]}')
    try:
        connection = seal.unseal(os.environ["ROWVIOLI_KEY_FILE"], t["key_id"], t["source"], t["connection"])
    except Exception as e:
        raise Exception(f"the connection of source {t['source']} cannot be decrypted on worker {t['worker']}: {e}")
    t["secrets"] = secrets(connection)
    batches = connector.read(connection, t["source_table"], t["options"])
    with conn.cursor() as c:
        return c.adbc_ingest("_stage", stream(batches), mode="create", temporary=True)


def stream(batches):
    """The driver's ingest needs the schema before the first batch; a connector may return any iterator."""
    if isinstance(batches, pa.RecordBatchReader):
        return batches
    batches = iter(batches)
    first = next(batches, None)
    if first is None:
        raise Exception("the source delivered zero rows")
    return pa.RecordBatchReader.from_batches(first.schema, itertools.chain([first], batches))


def diff(conn, t, staged, mirror):
    """Step 5: the rows that differ into the TEMP table _diff (README "Comparing in the target"), every column
    list by name. Returns the counts."""
    had = dict(mirror)
    s = ", ".join("s." + quote(c) for c, _ in staged)
    # a new column is null in the mirror once added, so a row differs only if the source has a value there
    m = ", ".join(f"m.{quote(c)}" if c in had else f"NULL::{type}" for c, type in staged)
    key = [quote(k) for k in t["key"]]
    on = " AND ".join(f"s.{k} = m.{k}" for k in key)
    if not mirror:
        sql(conn, f"CREATE TEMP TABLE _diff AS SELECT 'I'::text AS _op, {s} FROM _stage s")
    else:
        sql(conn, f"""CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in staged)}) AS
            SELECT 'D'::text AS _op, {m} FROM {t['mirror']} m WHERE NOT EXISTS (SELECT FROM _stage s WHERE {on})
            UNION ALL
            SELECT CASE WHEN m.{key[0]} IS NULL THEN 'I' ELSE 'U' END, {s}
              FROM _stage s LEFT JOIN {t['mirror']} m ON {on}
             WHERE m.{key[0]} IS NULL OR ROW({s}) IS DISTINCT FROM ROW({m})""")
    counts = dict(sql(conn, "SELECT _op, count(*) FROM _diff GROUP BY _op"))
    return {"inserted": counts.get("I", 0), "updated": counts.get("U", 0), "deleted": counts.get("D", 0)}


def publish(conn, t, staged, mirror, rows_read, counts):
    """Step 6, one transaction: new columns, change log, mirror, loaded_at, attempts and the run's row."""
    names = ", ".join(quote(c) for c, _ in staged)
    new = not mirror
    if new:
        # in a transaction of its own under a lock on its name, because two first runs of a source race on
        # IF NOT EXISTS; the one-number lock never counts as a table lock
        sql(conn, "SELECT pg_advisory_lock(hashtext($1))", [t["schema"]])
        sql(conn, f"CREATE SCHEMA IF NOT EXISTS {quote(t['schema'])}")
        sql(conn, "SELECT pg_advisory_unlock(hashtext($1))", [t["schema"]])
    sql(conn, "BEGIN")
    if new:  # created inside publishing, so a mirror never exists empty
        key = f", PRIMARY KEY ({', '.join(quote(k) for k in t['key'])})" if t["key"] else ""
        sql(conn, f"CREATE TABLE {t['mirror']} (LIKE _stage{key})")
    else:
        widen(conn, t["mirror"], staged, mirror)
    if t["key"]:
        if t["log"]:
            log = sql(conn, COLUMNS, [t["log_table"]])
            if log:
                widen(conn, t["log_table"], staged, log)
            else:
                sql(conn, f"CREATE TABLE {t['log_table']} (_run bigint, _op text, LIKE {t['mirror']})")
            sql(conn, f"INSERT INTO {t['log_table']} (_run, _op, {names}) SELECT $1, _op, {names} FROM _diff",
                [t["run"]])
        on = " AND ".join(f"d.{quote(k)} = m.{quote(k)}" for k in t["key"])
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


def widen(conn, table, staged, existing):
    """Decision 17: adds the source's columns the table lacks. The exclusive lock this takes waits behind a
    long-reading consumer, so it gives up after lock_timeout and the run fails instead of hanging."""
    have = dict(existing)
    for name, type in staged:
        if name not in have:
            sql(conn, "SET LOCAL lock_timeout = '10s'")
            sql(conn, f"ALTER TABLE {table} ADD COLUMN {quote(name)} {type}")


def secrets(value):
    """Every text of a connection, and the password of a URL in it as written and decoded, since a driver may quote
    either (README "What happens to the decrypted connection")."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in secrets(v)]
    if isinstance(value, list):
        return [s for v in value for s in secrets(v)]
    if not isinstance(value, str):
        return []
    password = urlsplit(value).password if "://" in value else None
    return [value] + ([password, unquote(password)] if password else [])


def scrub(t, text):
    for secret in sorted(filter(None, t.get("secrets", [])), key=len, reverse=True):  # a whole URL before its parts
        text = text.replace(secret, "***")
    return text


def rowcount(conn, query):
    with conn.cursor() as c:
        c.execute(query)
        return c.rowcount


def fail(conn, t, reason):
    """The one way a run fails: the reason on the table and the run's row first, then the lock, which goes with
    the connection."""
    sql(conn, "ROLLBACK")  # outside a transaction only a warning
    sql(conn, "UPDATE _rowvioli.tables SET reason = $2 WHERE id = $1", [t["id"], reason])
    sql(conn, "UPDATE _rowvioli.runs SET status = 'failed', finished_at = clock_timestamp(), reason = $2"
              " WHERE run = $1", [t["run"], reason])
    return {"status": "failed", "reason": reason}


def say(**line):
    print(json.dumps(line), flush=True)


def orphaned(parent):
    """Decision 33: a worker killed hard takes its runs with it. An orphan gets a new parent, so the run process
    ends once its parent changes; its connection and lock go with it."""
    while os.getppid() == parent:
        time.sleep(1)
    os._exit(1)


def main(worker, source, table):
    threading.Thread(target=orphaned, args=[os.getppid()], daemon=True).start()
    conn = target.connect()
    t = claim(conn, worker, source, table)
    if t is None:
        return
    say(claimed=t["name"], run=t["run"], max_seconds=t["max_seconds"])
    try:
        answer = load(conn, t)
    except BaseException as e:  # everything, so no unscrubbed traceback reaches stderr (open point F4)
        answer = {"reason": scrub(t, str(e) or type(e).__name__)}
    if "reason" in answer:  # outside the except, so a failing fail() cannot print the unscrubbed error with it
        try:
            answer = fail(conn, t, answer["reason"])
        except Exception:  # the target dropped the connection: the lock went with it, nothing can be stored
            answer = {"status": "failed", "reason": "connection to the target lost"}
    say(table=t["name"], **answer)
    conn.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
