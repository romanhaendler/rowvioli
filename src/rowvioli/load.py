"""One run, in a process of its own (README "A run"): claim, stage, diff, publish, or fail.

Started by the worker loop as `python -m rowvioli.load <worker> <source> <table>`. It tells the worker on stdout,
one JSON object per line: {"claimed": <target table>, "run", "max_seconds"} right after the claim, before reading,
and {"table": <target table>, "status", ...counts or "reason"} at the end. It prints nothing if it claimed nothing.
"""
import itertools
import json
import os
import re
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

import pyarrow as pa

from . import contract, seal, target
from .target import CLAIMABLE, quote, sql

TABLE = """SELECT t.id, s.name AS source, s.type, s.connection, s.key_id, t.source_table, t.target_schema AS schema,
                  t.target_table AS "table", t.key, t.log, t.max_seconds, (s.options || t.options)::text AS options,
                  t.max_delete_share::float8 AS max_delete_share
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
        with conn.cursor() as c:
            c.execute(TABLE, [id])
            t = dict(zip([d[0] for d in c.description], c.fetchone()), run=run, worker=worker)
        sql(conn, "COMMIT")
    except BaseException:
        sql(conn, "ROLLBACK")
        raise
    t["options"] = json.loads(t["options"])  # the source's options, overridden by the table's
    t["name"] = f"{t['schema']}.{t['table']}"
    t["mirror"] = f"{quote(t['schema'])}.{quote(t['table'])}"
    t["log_table"] = f"{quote(t['schema'])}.{quote(t['table'] + '__log')}"
    t["history"] = f"{quote(t['schema'])}.{quote(t['table'] + '__history')}"
    return t


def load(conn, t):
    """Steps 2 to 6. Raises with the reason when the run fails."""
    rows_read = stage(conn, t)
    staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    mirror = sql(conn, COLUMNS, [t["mirror"]])  # empty before the first run
    log_columns = sql(conn, COLUMNS, [t["log_table"]])
    check(conn, t, staged, mirror, log_columns)
    counts = diff(conn, t, staged, mirror) if t["key"] else None
    if mirror:
        check_delete_share(conn, t, rows_read, counts)
    return publish(conn, t, staged, mirror, log_columns, rows_read, counts)


def check(conn, t, staged, mirror, log_columns):
    """Step 4 (README "Checks before publishing"). A new column passes, publish adds it (decision 17)."""
    types = dict(staged)
    for name, type in mirror:
        if name not in types:
            raise Exception(f"column {name} is missing in the source")
        if types[name] != type:
            raise Exception(f"column {name} has changed its type from {type} to {types[name]}")
    key = t["key"] or []
    drop = (f"drop it with its history view (DROP TABLE {t['log_table']} CASCADE), or rename both"
            + (" with the mirror" if mirror else ""))
    if mirror:
        primary_key = [k for (k,) in sql(conn, PRIMARY_KEY, [t["mirror"]])]
        if primary_key != key:
            raise Exception(f"the key {key} differs from the mirror's primary key {primary_key}"
                            + (f"; the change log {t['name']}__log exists: {drop}" if log_columns else ""))
    # a change log that exists is complete: a run that would leave it behind its mirror, or lay a new mirror's
    # history over it, fails
    why = ("this run would not write to it (log = false or no key)" if not (key and t["log"])
           else "its mirror is missing" if not mirror else None)
    if log_columns and why:
        raise Exception(f"the change log {t['name']}__log exists and {why}: {drop}")
    if key:
        # the diff, the change log and the history view carry them beside the table's columns
        for name in ["_op", "_run", "_loaded_at", "_valid_from", "_valid_to"] if t["log"] else ["_op"]:
            if name in types:
                raise Exception(f"column {name} is a name of the change log or the history view, so a table with a "
                                "key cannot have it")
        names = ", ".join(quote(k) for k in key)
        if sql(conn, f"SELECT 1 FROM _stage WHERE {' OR '.join(quote(k) + ' IS NULL' for k in key)} LIMIT 1"):
            raise Exception(f"a key column of ({names}) is null")
        if sql(conn, f"SELECT 1 FROM _stage GROUP BY {names} HAVING count(*) > 1 LIMIT 1"):
            raise Exception(f"a key combination of ({names}) occurs twice")


def check_delete_share(conn, t, rows_read, counts):
    """After step 5: a broken source must not empty the mirror in a perfectly consistent way (decision 18).
    Without a key the shrinkage counts."""
    before = sql(conn, f"SELECT count(*) FROM {t['mirror']}")[0][0]
    gone = counts["deleted"] if counts else before - rows_read
    if before and gone / before > t["max_delete_share"]:
        raise Exception(f"{round(100 * gone / before)} % of the rows would be deleted")


def stage(conn, t):
    """Opens the connection, calls the connector and fills the TEMP staging table chunk by chunk. Returns the
    number of rows read."""
    connector = contract.connector(t["type"], f" on worker {t['worker']}")
    try:
        connection = seal.unseal(os.environ["ROWVIOLI_KEY_FILE"], t["key_id"], t["source"], t["connection"])
    except Exception as e:
        raise Exception(f"the connection of source {t['source']} cannot be decrypted on worker {t['worker']}: {e}")
    t["values"] = connection_values(connection)
    batches = stream(connector.read(connection, t["source_table"], t["options"]))
    with conn.cursor() as c:
        rows_read = c.adbc_ingest("_stage", batches, mode="create", temporary=True) if batches else 0
    if rows_read == 0:
        raise Exception("the source delivered zero rows")
    return rows_read


def stream(batches):
    """The driver's ingest needs the schema before the first batch; a connector may return any iterator. None for
    one without a batch."""
    if isinstance(batches, pa.RecordBatchReader):
        return batches
    batches = iter(batches)
    first = next(batches, None)
    if first is None:
        return None
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


def publish(conn, t, staged, mirror, log, rows_read, counts):
    """Step 6, one transaction: new columns, mirror, change log and its view, loaded_at, attempts and the run's
    row."""
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
        on = " AND ".join(f"d.{quote(k)} = m.{quote(k)}" for k in t["key"])
        sql(conn, f"DELETE FROM {t['mirror']} m USING _diff d WHERE d._op IN ('D', 'U') AND {on}")
        sql(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _diff WHERE _op IN ('I', 'U')")
        if t["log"]:
            write_log(conn, t, staged, log, names)
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


def write_log(conn, t, staged, log, names):
    """After the mirror is published, in the same transaction: a log that exists gets the diff, a new one begins
    with the whole mirror, so that replaying a log from its first row always gives the mirror. The history view is
    created when missing and replaced when the log got a column; otherwise it is not touched, so takes no lock."""
    if log:
        widened = widen(conn, t["log_table"], staged, log)
        rows = f"SELECT _op, {names} FROM _diff"
    else:
        sql(conn, f"CREATE TABLE {t['log_table']} (_run bigint, _op text, _loaded_at timestamptz, LIKE {t['mirror']})")
        rows = f"SELECT 'I', {names} FROM {t['mirror']}"
    # now() is the transaction's moment, the one that goes into tables.loaded_at
    sql(conn, f"INSERT INTO {t['log_table']} (_run, _loaded_at, _op, {names}) SELECT $1, now(), * FROM ({rows}) r",
        [t["run"]])
    if log and not widened and sql(conn, "SELECT to_regclass($1) IS NOT NULL", [t["history"]])[0][0]:
        return
    columns = ", ".join(quote(c) for c, _ in sql(conn, COLUMNS, [t["log_table"]])
                        if c not in ("_run", "_op", "_loaded_at"))
    key = ", ".join(quote(k) for k in t["key"])
    # _valid_to is the next version's moment, computed before the D rows are left out; the table's columns come
    # last so that a new one can be appended by replacing the view
    sql(conn, f"""CREATE OR REPLACE VIEW {t['history']} AS
        SELECT _valid_from, _valid_to, {columns} FROM (
            SELECT _op, _loaded_at AS _valid_from,
                   lead(_loaded_at) OVER (PARTITION BY {key} ORDER BY _loaded_at) AS _valid_to, {columns}
              FROM {t['log_table']}) h
         WHERE _op <> 'D'""")


def widen(conn, table, staged, existing):
    """Decision 17: adds the source's columns the table lacks. The exclusive lock this takes waits behind a
    long-reading consumer, so it gives up after lock_timeout and the run fails instead of hanging. Says whether
    it added one."""
    have = dict(existing)
    new = [(name, type) for name, type in staged if name not in have]
    for name, type in new:
        sql(conn, "SET LOCAL lock_timeout = '10s'")
        sql(conn, f"ALTER TABLE {table} ADD COLUMN {quote(name)} {type}")
    return bool(new)


# the password of an ODBC connection string: `PWD=secret` or `PWD={se;cret}` with `}}` for a `}`
ODBC_PASSWORD = re.compile(r"(?:^|;)\s*(?:PWD|Password)\s*=\s*(\{(?:[^}]|\}\})*\}|[^;]*)", re.I)


def connection_values(value):
    """Every text of a connection, and the password of a URL or an ODBC string in it as written and decoded, since a
    driver may quote either (README "What happens to the decrypted connection")."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in connection_values(v)]
    if isinstance(value, list):
        return [s for v in value for s in connection_values(v)]
    if not isinstance(value, str):
        return []
    password = urlsplit(value).password if "://" in value else None
    odbc = [m[1].strip() for m in ODBC_PASSWORD.finditer(value)]
    return ([value] + ([password, unquote(password)] if password else [])
            + odbc + [p[1:-1].replace("}}", "}") for p in odbc if p.startswith("{")])


def scrub(values, text):
    """`text` with each of `values` replaced by `***`."""
    for value in sorted(filter(None, values), key=len, reverse=True):  # a whole URL before its parts
        text = text.replace(value, "***")
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
    print(json.dumps(line), file=CHANNEL, flush=True)


CHANNEL = sys.stdout  # the line to the worker; main takes it away from fd 1


def orphaned(parent):
    """Decision 33: a worker killed hard takes its runs with it. An orphan gets a new parent, so the run process
    ends once its parent changes; its connection and lock go with it."""
    while os.getppid() == parent:
        time.sleep(1)
    os._exit(1)


def main(worker, source, table):
    global CHANNEL
    # a library may write to stdout, DuckDB its progress bar: only say() reaches the worker, the rest is dropped
    CHANNEL = os.fdopen(os.dup(1), "w")
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    threading.Thread(target=orphaned, args=[os.getppid()], daemon=True).start()
    conn = target.connect()
    t = claim(conn, worker, source, table)
    if t is None:
        return
    say(claimed=t["name"], run=t["run"], max_seconds=t["max_seconds"])
    try:
        answer = load(conn, t)
    except BaseException as e:  # everything, so no unscrubbed traceback reaches stderr (open point F4)
        answer = {"reason": scrub(t.get("values", []), str(e) or type(e).__name__)}
    if "reason" in answer:  # outside the except, so a failing fail() cannot print the unscrubbed error with it
        try:
            answer = fail(conn, t, answer["reason"])
        except Exception:  # the target dropped the connection: the lock went with it, nothing can be stored
            answer = {"status": "failed", "reason": "connection to the target lost"}
    say(table=t["name"], **answer)
    conn.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
