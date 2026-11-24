"""One run, in a process of its own (docs/loading.md "A run"): claim, stage, diff, publish, or fail.

Started by the worker loop as `python -m rowvioli.load <worker> <source> <table>`, with a pipe on stdin that
ends with the worker. It tells the worker on stdout,
one JSON object per line: {"claimed": <target table>, "run", "max_seconds"} right after the claim, before reading,
and {"table": <target table>, "status", ...counts or "reason"} at the end. It prints nothing if it claimed nothing.
"""
import importlib.metadata
import itertools
import json
import os
import re
import signal
import sys
import threading
import time
from urllib.parse import unquote

import pyarrow as pa
import pyarrow.compute as pc

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
    """In one transaction under the counting lock (docs/target.md "How Postgres counts"): takes the table lock of the
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
        # the lock was free, so a run of this table that still says `running` is dead (the status shows `worker lost`)
        sql(conn, """UPDATE _rowvioli.runs SET status = 'failed', finished_at = clock_timestamp(), reason = 'worker lost'
                      WHERE run = (SELECT max(run) FROM _rowvioli.runs WHERE "table" = $1) AND status = 'running'""",
            [id])  # only its newest can be: the one row, not all of runs, under the lock all claims share
        [(run,)] = sql(conn, """INSERT INTO _rowvioli.runs ("table", worker, definition, program_version)
                                SELECT $1, $2, definition, $3 FROM _rowvioli.meta RETURNING run""",
                       [id, worker, importlib.metadata.version("rowvioli")])
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
    t["step"] = "reading the source"
    rows_read = stage(conn, t)
    t["step"] = "checking the data"
    delivered = staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    mirror = sql(conn, COLUMNS, [t["mirror"]])  # empty before the first run
    log_columns = sql(conn, COLUMNS, [t["log_table"]])
    # decision 3: a source without a catalog has no column that goes; one its data lack this run is empty. One a
    # change log lacks is not known to be from the source, and check() stops it rather than empty a person's column
    if t["type"] in ("file", "rest") and (missing := [(n, type) for n, type in mirror if n not in dict(staged)
                                                      and (not log_columns or n in dict(log_columns))]):
        sql(conn, "ALTER TABLE _stage " + ", ".join(f"ADD {quote(n)} {type}" for n, type in missing))
        staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    staged = fit(conn, t, staged, mirror, log_columns)
    plan = check(conn, t, staged, mirror, log_columns)
    t["step"] = "comparing with the mirror"
    counts = diff(conn, t, staged, mirror, plan) if t["key"] else None
    if mirror:  # under another key the mirror is replaced as a whole, and only its shrinkage counts
        check_delete_share(conn, t, rows_read, None if plan["key"] else counts)
    t["step"] = "publishing"
    return publish(conn, t, staged, delivered, mirror, log_columns, rows_read, counts, plan)


def check(conn, t, staged, mirror, log_columns):
    """Step 4 (docs/loading.md "Checks before publishing") and the plan (decision 12): what the run does to the columns
    besides adding the new ones, which publish adds (decision 2). Every stop a rule makes is here, before anything is
    written. The plan: `gone`, the mirror's columns that leave it and stay in the change log (decision 3),
    `retired`, the change log's columns that keep their values under another name as one of another family comes
    (decision 2), old name to new, and `key` when the mirror's primary key is not the definition's (decision 7): the
    primary key it `was`, whether the change is `by` the definition or the primary key was changed by hand and is put
    back, and whether a change `log` exists."""
    types, logged = dict(staged), dict(log_columns)
    plan = {"gone": [], "retired": {}, "key": {}}
    for name, type in mirror:
        if name not in types:
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"column {name} is missing in the source; without a change log its values are nowhere "
                                f"else, so a person drops it: ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            if name not in logged:
                raise Exception(f"column {name} of the mirror is not in the change log, so it is not known to be from "
                                "the source; drop it from the mirror, or add it to the change log too and the next run "
                                "takes it out of the mirror")
            plan["gone"].append(name)
        elif types[name] != type:
            raise Exception(f"column {name} has changed its type from {type} to {types[name]}")
    had = dict(mirror)
    way = ("rename that column of the change log and drop its history view, which the next run creates again: "
           f"ALTER TABLE {t['log_table']} RENAME COLUMN {{}} TO <another name>; DROP VIEW {t['history']}")
    for name, type in staged:
        if name in had or name not in logged:
            continue
        if (retired := re.fullmatch(r"(.+)__\d+", name)) and retired[1] in logged:
            raise Exception(f"column {name} of the source has the name under which the change log keeps the old "
                            f"values of {retired[1]}: " + way.format(quote(name)))
        if family(logged[name]) == family(type):
            continue
        new = f"{name}__{t['run']}"
        taken = new in logged or new in types  # by the source too, in this very run
        if taken or len(new.encode()) > 63:
            raise Exception(f"column {name} of the change log is to keep its old values under {new}, a name that is "
                            + ("taken" if taken else "longer than 63 bytes") + ": " + way.format(quote(name)))
        plan["retired"][name] = new
    key = t["key"] or []
    drop = (f"drop it with its history view (DROP TABLE {t['log_table']} CASCADE), or rename both"
            + (" with the mirror" if mirror else ""))
    if mirror:
        primary_key = [k for (k,) in sql(conn, PRIMARY_KEY, [t["mirror"]])]
        if primary_key and not key and log_columns:  # the program does not end a change log
            raise Exception(f"the definition has no key any more, the mirror's primary key is {primary_key}: "
                            "put the key back, or give the table another target_table; to load it without a key, "
                            f"drop the change log {t['name']}__log with its history view "
                            f"(DROP TABLE {t['log_table']} CASCADE) and the mirror")
        if set(primary_key) != set(key):  # the same columns in another order are the same key (story 20)
            # decision 7: the key the last run recorded is the definition's, so a person changed the primary key
            recorded = sql(conn, 'SELECT "column", "key" FROM _rowvioli.columns WHERE id = $1', [t["id"]])
            hand = bool(recorded) and {c for c, k in recorded if k is not None} == set(key)
            plan["key"] = {"was": primary_key, "by": "hand" if hand else "definition", "log": bool(log_columns)}
    # a change log that exists is complete: a run that would leave it behind its mirror, or lay a new mirror's
    # history over it, fails
    why = ("this run would not write to it (log = false or no key)" if not (key and t["log"])
           else "its mirror is missing" if not mirror else None)
    if log_columns and why:
        raise Exception(f"the change log {t['name']}__log exists and {why}: {drop}")
    # decision 9: one branch over a change log written under two keys gives wrong rows, so the record says them
    if log_columns and stretches(conn, t) is None and (noted := sql(
            conn, """SELECT substr(note, length($2) + 1) FROM _rowvioli.columns__log WHERE id = $1
                      AND starts_with(note, $2) ORDER BY _loaded_at DESC LIMIT 1""", [t["id"], KEYS_NOTE])):
        raise Exception(f"the comment on column _op of the change log {t['name']}__log, which says the keys it was "
                        "written under, is missing or unreadable, and the key has changed: put it back, "
                        f"COMMENT ON COLUMN {t['log_table']}._op IS '{noted[0][0].replace(chr(39), chr(39) * 2)}'")
    if key:
        # the diff, the change log and the history view carry them beside the table's columns
        for name in ["_op", "_run", "_loaded_at", "_valid_from", "_valid_to"] if t["log"] else ["_op"]:
            if name in types:
                way = "; log = false frees it" if name != "_op" else "; _op cannot be freed"
                raise Exception(f"column {name} is a name of the change log or the history view, so a table with a "
                                f"key cannot have it{way}")
        names = ", ".join(quote(k) for k in key)
        if sql(conn, f"SELECT 1 FROM _stage WHERE {' OR '.join(quote(k) + ' IS NULL' for k in key)} LIMIT 1"):
            raise Exception(f"a key column of ({names}) is null")
        if sql(conn, f"SELECT 1 FROM _stage GROUP BY {names} HAVING count(*) > 1 LIMIT 1"):
            raise Exception(f"a key combination of ({names}) occurs twice")
    return plan


# decision 4: the families of types; every other type, without its modifier, is a family of its own
FAMILIES = {"smallint": "exact", "integer": "exact", "bigint": "exact", "numeric": "exact", "real": "float",
            "double precision": "float", "date": "time", "timestamp without time zone": "time"}


def family(type):
    base = re.sub(r"\(.*?\)", "", type)  # numeric(10,2), timestamp(3) without time zone
    return FAMILIES.get(base, base)


def fit(conn, t, staged, mirror, log_columns):
    """A staged column whose type differs from the target's only in its precision or scale (numeric and
    numeric(10,2)) counts as the mirror's, so that the comparison happens in the target type, when every value
    passes unchanged into the mirror and the change log (decision 49). Returns the staged columns with the types
    they are checked and published in."""
    pairs = [(table, name, into) for table, columns in ((t["name"], mirror), (t["name"] + "__log", log_columns))
             for name, type in staged if (into := dict(columns).get(name, type)) != type]
    if not pairs:
        return staged
    # in one query: which differ only in their modifier, and which target has none, so that a cast changes no value
    kinds = sql(conn, """SELECT (v->>0)::regtype = (v->>1)::regtype, (v->>1)::regtype::text = v->>1
                           FROM jsonb_array_elements($1::jsonb) WITH ORDINALITY e(v, n) ORDER BY n""",
                [json.dumps([[dict(staged)[name], into] for _, name, into in pairs])])
    misfit(conn, [p for p, (same, plain) in zip(pairs, kinds) if same and not plain])
    # the others are a real change, which check() catches. The staging table is not altered: numbers compare equal
    # whatever their modifier, and the mirror's type applies on insert, where it now changes no value
    taken = {name: into for (table, name, into), (same, _) in zip(pairs, kinds) if same and table == t["name"]}
    # a column back in its family takes the change log's type, as one of the mirror keeps the mirror's (cases A12),
    # and a value it would change stops the run rather than being cut
    had, types = dict(mirror), dict(staged)
    back = [(table, name, into) for table, name, into in pairs
            if table != t["name"] and name not in had and family(into) == family(types[name])]
    misfit(conn, back)
    taken.update({name: into for _, name, into in back})
    return [(name, taken.get(name, type)) for name, type in staged]


def misfit(conn, columns):
    """Fails on the first value of the (table, column, type) `columns` that its type would change, in one scan."""
    if not columns:
        return
    changed = [f"{quote(name)}::{type} IS DISTINCT FROM {quote(name)}" for _, name, type in columns]
    values = ", ".join(f"CASE WHEN {c} THEN {quote(name)}::text END" for c, (_, name, _) in zip(changed, columns))
    try:
        row = sql(conn, f"SELECT {values} FROM _stage WHERE {' OR '.join(changed)} LIMIT 1")
    except Exception as e:  # a value too large for the precision raises instead; column by column finds which
        if len(columns) > 1:
            for column in columns:
                misfit(conn, [column])
        row = [[reason_line([], e, "checking the data")]]
    for (table, name, type), value in zip(columns, row[0] if row else []):
        if value is not None:
            raise Exception(f"column {name} holds a value that its type {type} in {table} does not hold ({value})")


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
    sql(conn, "UPDATE _rowvioli.runs SET driver_version = $2 WHERE run = $1",
        [t["run"], getattr(connector, "driver_version", None)])
    try:
        connection = seal.unseal(os.environ["ROWVIOLI_KEY_FILE"], t["key_id"], t["source"], t["connection"])
    except Exception as e:
        raise Exception(f"the connection of source {t['source']} cannot be decrypted on worker {t['worker']}: {e}")
    # a directory is no secret, and a reason without it is not readable (decision 47)
    t["values"] = connection_values(connection, ("path",) if t["type"] == "file" else ())
    options = dict(t["options"])
    if isinstance(c := options.get("columns"), list) and all(isinstance(p, list) and len(p) == 2 for p in c):
        options["columns"] = dict(c)  # a dict is stored as pairs (definition.ordered), any other value as written
    batches = stream(connector.read(connection, t["source_table"], options))
    if batches is None:
        raise Exception("the connector delivered nothing, not even the columns")
    if (gone := [k for k in t["key"] or [] if k not in batches.schema.names]):
        raise Exception(f"table {t['source_table']} has no column {', '.join(gone)}; it has: "
                        + ", ".join(batches.schema.names))
    with conn.cursor() as c:
        # the driver creates every decimal as numeric; Arrow's decimal128 keeps its precision and scale (decision 49).
        # A scale below 0 or above the precision needs Postgres 15 in the target: such a column stays numeric.
        exact = {f.name: f"numeric({f.type.precision}, {f.type.scale})" for f in batches.schema
                 if pa.types.is_decimal128(f.type) and 0 <= f.type.scale <= f.type.precision}
        # a reader without batches: Arrow cannot make an empty array of a list of an extension type
        empty = pa.RecordBatchReader.from_batches(batches.schema, [])
        c.adbc_ingest("_driver" if exact else "_stage", empty, mode="create", temporary=True)
        if exact:  # a table made AS SELECT takes milliseconds, an ALTER of 300 columns seconds
            sql(conn, "CREATE TEMP TABLE _stage AS SELECT " + ", ".join(
                f"{quote(n)}::{exact[n]} AS {quote(n)}" if n in exact else quote(n) for n in batches.schema.names)
                + " FROM _driver")
            sql(conn, "DROP TABLE _driver")
        rows_read = c.adbc_ingest("_stage", without_nul(batches), mode="append", temporary=True)
    # zero rows protect a mirror that has rows; a first load or an empty mirror publishes them
    if rows_read == 0 and t["max_delete_share"] < 1 and sql(conn, "SELECT to_regclass($1)", [t["mirror"]])[0][0] and \
            sql(conn, f"SELECT 1 FROM {t['mirror']} LIMIT 1"):
        raise Exception("the source delivered zero rows; max_delete_share = 1.0 allows an empty table")
    # json has no equality, so the comparison could not run; the driver writes Arrow's json only as json
    jsonb = {"json": "jsonb", "json[]": "jsonb[]"}
    to_jsonb = [f"ALTER {quote(n)} TYPE {jsonb[type]} USING {quote(n)}::{jsonb[type]}"
                for n, type in sql(conn, COLUMNS, ["pg_temp._stage"]) if type in jsonb]
    if to_jsonb:
        sql(conn, "ALTER TABLE _stage " + ", ".join(to_jsonb))
    return rows_read


def without_nul(batches):
    """Postgres text cannot hold 0x00, so there is no faithful way to keep it: it is removed (decision 51)."""
    # shortcut: only top-level string columns, a NUL inside a list or struct still fails the run, upgrade when a source needs it
    text = [i for i, f in enumerate(batches.schema) if pa.types.is_string(f.type) or pa.types.is_large_string(f.type)]

    def clean():
        for b in batches:
            for i in text:
                b = b.set_column(i, batches.schema.field(i), pc.replace_substring(b.column(i), "\x00", ""))
            yield b
    return pa.RecordBatchReader.from_batches(batches.schema, clean())


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


def diff(conn, t, staged, mirror, plan):
    """Step 5, by the plan (decision 13): the rows that differ into the TEMP table _diff (docs/target.md "Comparing in
    the target"), over the columns of staging table and mirror together, every column list by name. Returns the
    counts."""
    had, staging = dict(mirror), dict(staged)
    columns = staged + [(c, had[c]) for c in plan["gone"]]
    # a new column is null in the mirror once added, and one that went is null in the source, so a row differs only
    # if the other side has a value there
    s = ", ".join(f"s.{quote(c)}" if c in staging else f"NULL::{type}" for c, type in columns)
    m = ", ".join(f"m.{quote(c)}" if c in had else f"NULL::{type}" for c, type in columns)
    key = [quote(k) for k in t["key"]]
    on = " AND ".join(f"s.{k} = m.{k}" for k in key)
    if not mirror or plan["key"].get("by") == "definition":  # under another key: every old row goes, every new comes
        old = f"SELECT 'D'::text, {m} FROM {t['mirror']} m UNION ALL " if mirror else ""
        sql(conn, f"CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in columns)}) AS "
                  f"{old}SELECT 'I'::text, {s} FROM _stage s")
    else:
        sql(conn, f"""CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in columns)}) AS
            SELECT 'D'::text AS _op, {m} FROM {t['mirror']} m WHERE NOT EXISTS (SELECT FROM _stage s WHERE {on})
            UNION ALL
            SELECT CASE WHEN m.{key[0]} IS NULL THEN 'I' ELSE 'U' END, {s}
              FROM _stage s LEFT JOIN {t['mirror']} m ON {on}
             WHERE m.{key[0]} IS NULL OR ROW({s}) IS DISTINCT FROM ROW({m})""")
    counts = dict(sql(conn, "SELECT _op, count(*) FROM _diff GROUP BY _op"))
    return {"inserted": counts.get("I", 0), "updated": counts.get("U", 0), "deleted": counts.get("D", 0)}


def publish(conn, t, staged, delivered, mirror, log, rows_read, counts, plan):
    """Step 6, one transaction in the order of decision 14: the plan, new columns, mirror, change log and its view,
    the columns table, loaded_at, attempts and the run's row. Raises, so nothing is published, when the table's row
    no longer gives it this target name."""
    names = ", ".join(quote(c) for c, _ in staged)
    logged = ", ".join(quote(c) for c in [*dict(staged), *plan["gone"]])
    new = not mirror
    if new:
        # in a transaction of its own under a lock on its name, because two first runs of a source race on
        # IF NOT EXISTS; the one-number lock never counts as a table lock
        sql(conn, "SELECT pg_advisory_lock(hashtext($1))", [t["schema"]])
        if not sql(conn, "SELECT 1 FROM pg_namespace WHERE nspname = $1", [t["schema"]]):  # else no CREATE right needed
            sql(conn, f"CREATE SCHEMA IF NOT EXISTS {quote(t['schema'])}")
        sql(conn, "SELECT pg_advisory_unlock(hashtext($1))", [t["schema"]])
    changes = {}
    if any(plan.values()):  # anything but added columns
        lock(conn, t)
        changes = carry_out(conn, t, plan)
    else:
        sql(conn, "BEGIN")
    if new:  # created inside publishing, so a mirror never exists empty
        key = f", PRIMARY KEY ({', '.join(quote(k) for k in t['key'])})" if t["key"] else ""
        sql(conn, f"CREATE TABLE {t['mirror']} (LIKE _stage{key})")
    else:
        widen(conn, t["mirror"], staged, mirror)
    if t["key"] and plan["key"].get("by") != "definition":
        on = " AND ".join(f"d.{quote(k)} = m.{quote(k)}" for k in t["key"])
        kept = only = ""
        if plan["gone"]:  # a row that differs only in a column that went keeps its place in the mirror (story 5)
            ds, ms = (", ".join(f"{a}.{quote(c)}" for c, _ in staged) for a in "dm")
            kept = f" AND (d._op = 'D' OR ROW({ds}) IS DISTINCT FROM ROW({ms}))"
            only = f" AND NOT EXISTS (SELECT FROM {t['mirror']} m WHERE {on})"
        sql(conn, f"DELETE FROM {t['mirror']} m USING _diff d WHERE d._op IN ('D', 'U') AND {on}{kept}")
        sql(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _diff d WHERE _op IN ('I', 'U'){only}")
    else:  # without a key, or under another key (decision 7): replaced as a whole
        deleted = rowcount(conn, f"DELETE FROM {t['mirror']}")
        counts = {"inserted": rowcount(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _stage"),
                  "updated": 0, "deleted": deleted}
    if t["key"] and plan["key"]:  # once the old rows are gone, which may hold the new key twice
        sql(conn, f"ALTER TABLE {t['mirror']} ADD PRIMARY KEY ({', '.join(quote(k) for k in t['key'])})")
    if t["key"] and t["log"]:  # the change log's columns under the names the plan gave them
        write_log(conn, t, staged, [(plan["retired"].get(n, n), type) for n, type in log], logged)
    record_columns(conn, t, delivered, mirror, log, changes)
    # the table lock guards the table, not its name, which an apply may have given to another table meanwhile
    # (decision 53). Last, so the row lock that holds off an apply until COMMIT is taken after every wait on a mirror
    if not sql(conn, """UPDATE _rowvioli.tables SET loaded_at = now(), attempts = 0
                         WHERE id = $1 AND enabled AND target_schema = $2 AND target_table = $3 RETURNING id""",
               [t["id"], t["schema"], t["table"]]):
        [(name, enabled)] = sql(conn, "SELECT target_schema || '.' || target_table, enabled FROM _rowvioli.tables"
                                      " WHERE id = $1", [t["id"]])
        raise Exception(f"the target name changed to {name} while this run loaded {t['name']}; nothing was published, "
                        f"the next run loads {name}" if enabled else
                        f"the table left the definition while this run loaded {t['name']}; nothing was published")
    sql(conn, """UPDATE _rowvioli.runs SET status = 'ok', finished_at = clock_timestamp(), rows_read = $2,
                        inserted = $3, updated = $4, deleted = $5 WHERE run = $1""",
        [t["run"], rows_read, counts["inserted"], counts["updated"], counts["deleted"]])
    sql(conn, "COMMIT")
    return {"status": "ok", **counts}


def lock(conn, t):
    """Decision 14: opens the publishing transaction holding mirror, change log and history view, taken in one
    statement that does not wait and tried again for up to ten seconds. A run that waited for one while holding
    another could deadlock with a consumer who reads them in another order (story 43)."""
    objects = ", ".join(n for n in (t["mirror"], t["log_table"], t["history"])
                        if sql(conn, "SELECT to_regclass($1) IS NOT NULL", [n])[0][0])
    end = time.monotonic() + 10
    while True:
        sql(conn, "BEGIN")
        try:
            sql(conn, f"LOCK TABLE {objects} IN ACCESS EXCLUSIVE MODE NOWAIT")
            return
        except Exception as e:
            sql(conn, "ROLLBACK")
            if getattr(e, "sqlstate", None) != "55P03":  # lock_not_available
                raise
            if time.monotonic() > end:
                raise Exception(f"{t['name']}, its change log or its history view stayed in use for 10 s, so its "
                                "columns could not change; the next run tries again") from None
            time.sleep(0.1)


# what Postgres drops with a column without a word (decision 22): indexes, constraints, the grants on the column
DROPS_WITH = """
    SELECT concat_ws(', ', (SELECT string_agg(pg_describe_object(classid, objid, 0), ', ' ORDER BY objid) FROM pg_depend
                             WHERE refclassid = 'pg_class'::regclass AND refobjid = a.attrelid
                               AND refobjsubid = a.attnum AND deptype = 'a'),
                           (SELECT string_agg(format('the grant of %s to %s', privilege_type, CASE grantee WHEN 0
                                   THEN 'public' ELSE grantee::regrole::text END), ', ') FROM aclexplode(a.attacl)))
      FROM pg_attribute a WHERE attrelid = $1::regclass AND attname = $2"""


def carry_out(conn, t, plan):
    """Decision 14, under the lock: the history view goes, since Postgres alters no column a view reads (write_log
    creates it again), then the plan. Returns what the columns table says beyond the catalogue (decisions 19, 22)."""
    alter(conn, f"the columns of {t['name']} change", f"DROP VIEW IF EXISTS {t['history']}")
    changes = {}
    for old, new in plan["retired"].items():
        sql(conn, f"ALTER TABLE {t['log_table']} RENAME COLUMN {quote(old)} TO {quote(new)}")
        changes[new] = {"was": old}
    if plan["key"]:  # decision 7: publish adds the new primary key once the rows are in
        was, key, by = plan["key"]["was"], t["key"] or [], plan["key"]["by"]
        note = (f"the primary key ({', '.join(was)}) was put back to the definition's ({', '.join(key)})"
                if by == "hand" else None)
        if was:
            [(name,)] = sql(conn, "SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass AND contype = 'p'",
                            [t["mirror"]])
            alter(conn, f"the key of {t['name']} would change from ({', '.join(was)}) to ({', '.join(key)})",
                  f"ALTER TABLE {t['mirror']} DROP CONSTRAINT {quote(name)}")
        if loose := [c for c in was if c not in key]:  # Postgres leaves NOT NULL behind, also where LIKE copied it
            for table in [t["mirror"], t["log_table"]] if plan["key"]["log"] else [t["mirror"]]:
                sql(conn, f"ALTER TABLE {table} " + ", ".join(f"ALTER {quote(c)} DROP NOT NULL" for c in loose))
        if by == "definition" and plan["key"]["log"]:  # a stretch of the change log begins under the new key
            [(now,)] = sql(conn, "SELECT now()::text")
            note = KEYS_NOTE + keys_of_log(conn, t, (stretches(conn, t) or [{"key": was}])
                                                           + [{"from": now, "key": key}])
        changes.update({c: {"by": by, "note": note} for c in {*was, *key}})
    for name in plan["gone"]:
        [(note,)] = sql(conn, DROPS_WITH, [t["mirror"], name])
        changes[name] = {"note": f"{note} went with it" if note else None}
        alter(conn, f"column {name} is gone from the source and would leave the mirror {t['name']}",
              f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
    return changes


KEYS_NOTE = "the change log's keys: "  # the note in the columns table of a change of key, before the comment's text


def stretches(conn, t):
    """Decision 9: the keys the change log was written under, as the comment on its column _op says them, a list of
    {"key": [...]} with "from", the moment it began, on every one but the first. None without a readable comment: such
    a change log has had one key."""
    [(text,)] = sql(conn, "SELECT col_description(to_regclass($1), (SELECT attnum FROM pg_attribute WHERE attrelid "
                          "= to_regclass($1) AND attname = '_op'))", [t["log_table"]])
    try:
        keys = json.loads(text)
        if keys and all(k["key"] and all(isinstance(c, str) for c in k["key"]) and isinstance(k.get("from", ""), str)
                        and ("from" in k) == (i > 0) for i, k in enumerate(keys)):
            return keys
    except Exception:  # anything but the list it should be: unreadable
        pass
    return None


def keys_of_log(conn, t, keys):
    """Writes `keys` as the comment on the change log's column _op; returns the text."""
    text = json.dumps(keys)
    sql(conn, f"COMMENT ON COLUMN {t['log_table']}._op IS '{text.replace(chr(39), chr(39) * 2)}'")
    return text


def alter(conn, why, statement):
    """A change Postgres refuses while a consumer's object depends on it: the reason says what would have changed,
    then Postgres's detail, which names the object (decision 15)."""
    try:
        sql(conn, statement)
    except Exception as e:
        details = {k.decode(): v.decode() for k, v in getattr(e, "details", None) or []}
        if details.get("PG_DIAG_SQLSTATE") != "2BP01":  # dependent_objects_still_exist
            raise
        raise Exception(f"{why}, but {details['PG_DIAG_MESSAGE_DETAIL'].replace(chr(10), '; ')}: change or drop "
                        "that, and the next run goes on") from None


def write_log(conn, t, staged, log, names):
    """After the mirror is published, in the same transaction: a log that exists gets the diff, a new one begins
    with the whole mirror, so that replaying a log from the last change of key always gives the mirror. The history
    view is created when missing and replaced when the log got a column; otherwise it is not touched, so takes no
    lock."""
    if log:
        widened = widen(conn, t["log_table"], staged, log)
        widened = follow(conn, t, log) or widened
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
    # decision 8: a branch per key, over its stretch of the change log: from its I rows at the moment it began, up to
    # the D rows at the moment the next began
    keys = stretches(conn, t) or [{"key": t["key"]}]
    moments = [f"'{k['from'].replace(chr(39), chr(39) * 2)}'::timestamptz" for k in keys[1:]]
    branches = []
    for i, k in enumerate(keys):
        cut = ([f"(_loaded_at > {moments[i - 1]} OR _loaded_at = {moments[i - 1]} AND _op = 'I')"] if i else []) + \
              ([f"(_loaded_at < {moments[i]} OR _loaded_at = {moments[i]} AND _op = 'D')"] if i < len(moments) else [])
        # _valid_to is the next version's moment, computed before the D rows are left out; the table's columns come
        # last so that a new one can be appended by replacing the view
        branches.append(f"""
        SELECT _valid_from, _valid_to, {columns} FROM (
            SELECT _op, _loaded_at AS _valid_from,
                   lead(_loaded_at) OVER (PARTITION BY {', '.join(quote(c) for c in k['key'])} ORDER BY _loaded_at)
                   AS _valid_to, {columns}
              FROM {t['log_table']}{' WHERE ' + ' AND '.join(cut) if cut else ''}) h
         WHERE _op <> 'D'""")
    sql(conn, f"CREATE OR REPLACE VIEW {t['history']} AS" + "\n        UNION ALL".join(branches))


def follow(conn, t, log):
    """Decision 20: a numeric type that a person widened in the mirror is followed in the change log, so that what the
    mirror holds fits it. The history view reads the column, so it goes first and the caller creates it again. Says
    whether it altered one."""
    def digits(type):  # before and after the point; unconstrained numeric holds all
        m = re.fullmatch(r"numeric\((\d+),(\d+)\)", type)
        return (int(m[1]) - int(m[2]), int(m[2])) if m else (float("inf"),) * 2 if type == "numeric" else None
    mirror = dict(sql(conn, COLUMNS, [t["mirror"]]))
    wider = [(name, into) for name, type in log if (into := mirror.get(name)) and into != type
             and digits(type) and digits(into) and all(a >= b for a, b in zip(digits(into), digits(type)))]
    if wider:
        sql(conn, "SET LOCAL lock_timeout = '10s'")
        sql(conn, f"DROP VIEW IF EXISTS {t['history']}")
        sql(conn, f"ALTER TABLE {t['log_table']} " + ", ".join(f"ALTER {quote(n)} TYPE {into}" for n, into in wider))
    return bool(wider)


def record_columns(conn, t, delivered, mirror, log, changes):
    """Decisions 17 to 22, last in publishing, in its transaction: what the columns of mirror and change log are now
    against what `_rowvioli.columns` says, as rows of `columns__log` with this transaction's moment. `mirror` and `log`
    are the columns as the run found them, so that what differs from the record without this run is by hand.
    `changes` gives fields of the plan by column name (`was`, `note`, `by`). Notifies on `rowvioli_schema` when
    anything but a first fill was recorded."""
    def state(mirror, log):
        return {**{n: (type, False) for n, type in log if n not in ("_run", "_op", "_loaded_at")},
                **{n: (type, True) for n, type in mirror}}
    found = state(mirror, log)
    now = state(sql(conn, COLUMNS, [t["mirror"]]), sql(conn, COLUMNS, [t["log_table"]]))
    key = {k: i + 1 for i, k in enumerate(t["key"] or [])}
    delivered = dict(delivered)
    with conn.cursor() as c:
        c.execute("""SELECT target_schema, target_table, "column", type, source_type, "key", mirror, was, "by", note,
                            to_regclass(format('%I.%I', target_schema, target_table)) IS NULL
                       FROM _rowvioli.columns WHERE id = $1""", [t["id"]])
        recorded = c.fetchall()
    names = ["target_schema", "target_table", "column", "type", "source_type", "key", "mirror", "was", "by", "note"]
    old = {r[2]: dict(zip(names, r)) for r in recorded if (r[0], r[1]) == (t["schema"], t["table"])}
    # a mirror renamed by hand: what was recorded under a name that is no table any more is closed
    rows = [{**dict(zip(names, r)), "op": "D", "by": "hand"} for r in recorded if r[10]]
    rows += [{**r, "op": "D", "by": "hand"} for name, r in old.items() if name not in now]
    for name, (type, in_mirror) in now.items():
        row = dict(target_schema=t["schema"], target_table=t["table"], column=name, type=type,
                   source_type=delivered.get(name, type), key=key.get(name), mirror=in_mirror, was=None, note=None)
        if (before := old.get(name)) is None:
            row.update(op="I", by="found" if not old else "source" if name not in found else "hand")
        else:
            # a mirror's column the change log lost by hand: the run adds it again, the state alone shows nothing
            hand = found.get(name) != (before["type"], before["mirror"]) or bool(log) and name not in dict(log) \
                or changes.get(name, {}).get("by") == "hand"  # a primary key put back: the record knew the key
            if not hand and all(before[f] == row[f] for f in ("type", "source_type", "key", "mirror")):
                continue
            row.update(op="U", by="hand" if hand else "source", was=before["was"])
        rows.append(row)
    if not rows:
        return
    for r in rows:
        if (r["target_schema"], r["target_table"]) == (t["schema"], t["table"]):
            r.update(changes.get(r["column"], {}))
    if any(r["by"] == "source" for r in rows):  # another reader gave these columns, perhaps, not the source
        [(differs, note)] = sql(conn, """
            SELECT (l.program_version, l.driver_version) IS DISTINCT FROM (c.program_version, c.driver_version),
                   format('program %s to %s, driver %s to %s', coalesce(l.program_version, 'none'),
                          coalesce(c.program_version, 'none'), coalesce(l.driver_version, 'none'),
                          coalesce(c.driver_version, 'none'))
              FROM _rowvioli.runs c LEFT JOIN LATERAL (SELECT program_version, driver_version FROM _rowvioli.runs
                    WHERE "table" = c."table" AND status = 'ok' AND run < c.run ORDER BY run DESC LIMIT 1) l ON true
             WHERE c.run = $1""", [t["run"]])
        for r in rows:
            if differs and r["by"] == "source":
                r.update({"by": "reader", "note": "; ".join(filter(None, [note, r["note"]]))})
    x = """jsonb_to_recordset($1::jsonb) AS x(op text, target_schema text, target_table text, "column" text,
                type text, source_type text, "key" int, mirror boolean, was text, "by" text, note text)"""
    changes = json.dumps(rows)
    fields = 'target_schema, target_table, "column", type, source_type, "key", mirror, was, "by", note'
    sql(conn, f"INSERT INTO _rowvioli.columns__log SELECT $2::bigint, op, now(), {fields}, $3::int FROM {x}",
        [changes, t["run"], t["id"]])
    sql(conn, f"""DELETE FROM _rowvioli.columns c USING {x} WHERE x.op = 'D'
                     AND (c.target_schema, c.target_table, c."column") = (x.target_schema, x.target_table, x."column")""",
        [changes])
    sql(conn, f"""INSERT INTO _rowvioli.columns SELECT {fields}, $2::int FROM {x} WHERE op <> 'D'
                  ON CONFLICT (target_schema, target_table, "column") DO UPDATE SET type = excluded.type,
                  source_type = excluded.source_type, "key" = excluded."key", mirror = excluded.mirror,
                  was = excluded.was, "by" = excluded."by", note = excluded.note, id = excluded.id""",
        [changes, t["id"]])
    if any(r["by"] != "found" for r in rows):
        sql(conn, "SELECT pg_notify('rowvioli_schema', json_build_object('schema', $1::text, 'table', $2::text,"
                  " 'run', $3::bigint)::text)", [t["schema"], t["table"], t["run"]])


def widen(conn, table, staged, existing):
    """Decision 17: adds the source's columns the table lacks. The exclusive lock this takes waits behind a
    long-reading consumer, so it gives up after lock_timeout and the run fails instead of hanging. Says whether
    it added one."""
    have = dict(existing)
    new = [(name, type) for name, type in staged if name not in have]
    for name, type in new:
        sql(conn, "SET LOCAL lock_timeout = '10s'")
        try:
            sql(conn, f"ALTER TABLE {table} ADD COLUMN {quote(name)} {type}")
        except Exception as e:
            if getattr(e, "sqlstate", None) != "54011":  # too_many_columns
                raise
            raise Exception(f"column {name} cannot be added to {table}: Postgres counts the columns once dropped "
                            "from a table towards its 1600; rewrite the table to free them, by dump and restore") \
                from None
    return bool(new)


# the password of an ODBC connection string: `PWD=secret` or `PWD={se;cret}` with `}}` for a `}`
ODBC_PASSWORD = re.compile(r"(?:^|;)\s*(?:PWD|Password)\s*=\s*(\{(?:[^}]|\}\})*\}|[^;]*)", re.I)


def url_password(url):
    """The password of a URL; urlsplit refuses a `[` in the host part (Invalid IPv6 URL), so the user info is cut by hand."""
    userinfo = re.split(r"[/?#]", url.partition("://")[2])[0].rpartition("@")[0]
    return userinfo.partition(":")[2] or None


def connection_values(value, readable=()):
    """Every text of a connection, and the password of a URL or an ODBC string in it as written and decoded, since a
    driver may quote either (docs/connections.md "What happens to the decrypted connection")."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in connection_values(v) if k not in readable or s != v]
    if isinstance(value, list):
        return [s for v in value for s in connection_values(v)]
    if not isinstance(value, str):
        return []
    password = url_password(value) if "://" in value else None
    odbc = [m[1].strip() for m in ODBC_PASSWORD.finditer(value)]
    return ([value] + ([password, unquote(password)] if password else [])
            + odbc + [p[1:-1].replace("}}", "}") for p in odbc if p.startswith("{")])


def target_secrets():
    """The password of the target's URL, written and decoded: its user and host stay readable in an error."""
    password = url_password(os.environ.get("ROWVIOLI_TARGET_URL") or "")
    return [password, unquote(password)] if password else []


# what ADBC and nanoarrow put before the server's message: the call that failed with its errno and Arrow's status,
# the statement (its SQL may hold quotes and lines)
WRAPPER = re.compile(r"^(?:[A-Z_]+: )?(?:\[libpq\] )?(?:nanoarrow call failed: )?"
                     r"(?:[A-Za-z]+\(.*?\) = \(\d+\) [^.]*\. [A-Za-z ]+: )?"
                     r"(?:Failed to (?:prepare query|execute query(?: '.*?')?|execute prepared statement): )?"
                     r"(?:PGRES_[A-Z_]+ )?(?:ERROR:\s+)?", re.S)


def reason_line(values, e, step):
    """The reason as it is stored, shown and logged: scrubbed, the first line of the driver's message without its
    wrapper, joined with the next when it ends in a colon. A message that holds a traceback gives the text before
    it, or the exception's own line (the traceback's last) when nothing is before it; ADBC cuts long messages, so
    the end may be missing. A line saying so, with the exception's type, when there is no message."""
    text = scrub(values, str(e)).strip()
    before, _, traceback = text.partition("Traceback (most recent call last)")
    before = re.sub(r"\s*Detail: Python exception:\s*$", "", before)
    first, *rest = (WRAPPER.sub("", before).strip() or traceback.strip().split("\n")[-1]).split("\n")
    line = f"{first} {rest[0].strip()}" if first.endswith(":") and rest else first
    return line.strip() or f"the driver gave no message while {step} ({type(e).__name__})"


def scrub(values, text):
    """`text` with each of `values` replaced by `***`: as written, stripped, and as repr writes it in quotes."""
    values = [w for v in values if v for w in (v, v.strip(), repr(v)[1:-1], repr(v.strip())[1:-1])]
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


def orphaned():
    """Decision 33: a worker killed hard takes its runs with it. Stdin is a pipe from the worker that it never
    writes to; it ends with the worker on every platform (a parent id does not change on Windows), and the run
    process ends with it; its connection and lock go too."""
    while os.read(0, 4096):  # not sys.stdin.buffer.read(): its lock aborts the interpreter if it exits meanwhile
        pass
    os._exit(1)


def main(worker, source, table):
    global CHANNEL
    if hasattr(signal, "SIGBREAK"):  # Ctrl+Break reaches the run processes too, and they are to finish (decision 33)
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    # a library may write to stdout, DuckDB its progress bar: only say() reaches the worker, the rest is dropped
    CHANNEL = os.fdopen(os.dup(1), "w")
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    threading.Thread(target=orphaned, daemon=True).start()
    conn = target.connect()
    t = claim(conn, worker, source, table)
    if t is None:
        return
    say(claimed=t["name"], run=t["run"], max_seconds=t["max_seconds"])
    try:
        answer = load(conn, t)
    except BaseException as e:  # everything, so no unscrubbed traceback reaches stderr (open point F4)
        answer = {"reason": reason_line(t.get("values", []), e, t.get("step", "claiming"))}
    if "reason" in answer:  # outside the except, so a failing fail() cannot print the unscrubbed error with it
        try:
            answer = fail(conn, t, answer["reason"])
        except Exception:  # the target dropped the connection: the lock went with it, nothing can be stored
            answer = {"status": "failed", "reason": "connection to the target lost"}
    say(table=t["name"], **answer)
    conn.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
