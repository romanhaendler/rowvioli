"""One run, in a process of its own (docs/loading.md "A run"): claim, stage, diff, publish, or fail.

Started by the worker loop as `python -m rowvioli.load <worker> <source> <table>`, with a pipe on stdin that
ends with the worker. It tells the worker on stdout,
one JSON object per line: {"claimed": <target table>, "run", "max_seconds"} right after the claim, before reading,
{"widening": <table and columns>} before a widening that may rewrite a table, and {"table": <target table>,
"status", ...counts or "reason"} at the end. It prints nothing if it claimed nothing.
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
    # decision 3: a file has no column that goes; one its data lack this run is empty. One a change log lacks, or
    # every one without a change log, is not known to be from the source, and check() stops it rather than empty a
    # person's column. One the definition says is renamed to a column the data have is renamed (decision 10). REST
    # delivers every column under `columns`, even one no row has: the definition is its catalog, and a column taken
    # out of it goes as one a database drops
    stated = {old for new, old in (t["options"].get("renamed") or {}).items()
              if new in dict(staged) and new not in dict(mirror)}
    if t["type"] == "file" and (missing := [(n, type) for n, type in mirror if n not in dict(staged)
                                            and n not in stated and n in dict(log_columns)]):
        sql(conn, "ALTER TABLE _stage " + ", ".join(f"ADD {quote(n)} {type}" for n, type in missing))
        staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    plan = check(conn, t, staged, mirror, log_columns)
    staged, plan["widen"] = fit(conn, t, staged, mirror, log_columns, plan["renamed"])
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
    back, and whether a change `log` exists. `renamed`, new name to old, the columns that keep their values and
    history under another name (decision 10), and `proven`, the note of each one the data proved."""
    types, logged, had = dict(staged), dict(log_columns), dict(mirror)
    way = ("rename that column of the change log and drop its history view, which the next run creates again: "
           f"ALTER TABLE {t['log_table']} RENAME COLUMN {{}} TO <another name>; DROP VIEW {t['history']}")
    # decision 10: a rename the definition states acts once its old column is gone and its new one has come
    renamed = {new: old for new, old in (t["options"].get("renamed") or {}).items() if old in had
               and old not in types and new in types and new not in had and (not log_columns or old in logged)}
    for new, old in renamed.items():
        stated = f"column {old} is renamed {new} in the table's definition"
        if family(had[old]) != family(types[new]):
            raise Exception(f"{stated}, but {had[old]} and {types[new]} are types of two families, so their values "
                            f"are not the same: take {new} out of renamed")
        if new in logged:
            raise Exception(f"{stated}, but the change log has a column {new} already: " + way.format(quote(new)))
    # the key after the renames: Postgres renames a column inside the primary key by itself (decision 7)
    moved = {old: new for new, old in renamed.items()}
    primary_key = [moved.get(k, k) for (k,) in sql(conn, PRIMARY_KEY, [t["mirror"]])] if mirror else []
    plan = {"renamed": renamed, "proven": {}, "gone": [], "retired": {}, "key": {}}
    # nothing is proven without a catalog, a key or a change log, nor joined by a key of another family, which stops below
    if t["key"] and t["log"] and log_columns and t["type"] not in ("file", "rest") \
            and set(primary_key) == set(t["key"]) \
            and all(family(had[renamed.get(k, k)]) == family(types[k]) for k in t["key"]):
        proofs = proven(conn, t, mirror, staged, log_columns, renamed)
        renamed.update({new: old for new, (old, _) in proofs.items()})
        plan["proven"] = {new: note for new, (_, note) in proofs.items()}
    unknown = ("column {} of the mirror is not in the change log, so it is not known to be from the source; drop it "
               "from the mirror, or add it to the change log too and the next run takes it out of the mirror")
    for name, type in mirror:
        if name in renamed.values():
            continue
        if name not in types:
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"column {name} is missing in the source; without a change log its values are nowhere "
                                f"else, so a person drops it: ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            if name not in logged:
                raise Exception(unknown.format(name))
            plan["gone"].append(name)
        elif family(types[name]) != family(type):  # another family goes and comes (decision 6); fit() did the same
            changed = f"column {name} has changed its type from {type} to {types[name]}"
            drop = ("so a person drops it and the next run adds it anew: "
                    f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            # where the definition names the columns it is the catalog; a file guesses the type of every other one
            if t["type"] == "file" and name not in dict(t["options"].get("columns") or {}):
                raise Exception(f"{changed}; a source without a catalog guesses its types, so pin it under columns "
                                "in the table's definition")
            if name in (t["key"] or []):
                raise Exception(f"{changed}, a type of another family in the key, so a row before cannot be told "
                                "from one after: give the table another target_table, which begins a new mirror")
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"{changed}; without a change log its values are nowhere else, {drop}")
            if name not in logged:  # a person's column under a name the source brings now: no run brings its values
                raise Exception(unknown.format(name))
            if family(logged[name]) != family(type):  # the mirror's type changed by hand (cases G4)
                raise Exception(f"column {name} of the mirror has the type {type}, of another family than the "
                                f"{types[name]} the source delivers, and a run does not change it back; drop it from "
                                f"the mirror and the next run brings it again: "
                                f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            plan["gone"].append(name)
    for name, type in staged:
        if name not in logged or name in had and name not in plan["gone"]:
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
        if primary_key and not key and log_columns:  # the program does not end a change log
            raise Exception(f"the definition has no key any more, the mirror's primary key is {primary_key}: "
                            "put the key back, or give the table another target_table; to load it without a key, "
                            f"drop the change log {t['name']}__log with its history view "
                            f"(DROP TABLE {t['log_table']} CASCADE) and the mirror")
        if set(primary_key) != set(key):  # the same columns in another order are the same key (story 20)
            # decision 7: the key the last run recorded is the definition's, so a person changed the primary key
            recorded = sql(conn, 'SELECT "column", "key" FROM _rowvioli.columns WHERE id = $1', [t["id"]])
            hand = bool(recorded) and {moved.get(c, c) for c, k in recorded if k is not None} == set(key)
            plan["key"] = {"was": primary_key, "by": "hand" if hand else "definition", "log": bool(log_columns)}
    # a change log that exists is complete: a run that would leave it behind its mirror, or lay a new mirror's
    # history over it, fails
    why = ("this run would not write to it (log = false or no key)" if not (key and t["log"])
           else "its mirror is missing" if not mirror else None)
    if log_columns and why:
        raise Exception(f"the change log {t['name']}__log exists and {why}: {drop}")
    # decision 9: one branch over a change log written under two keys gives wrong rows, so the record says them
    if log_columns and stretches(conn, t) is None and (noted := sql(
            conn, """SELECT substr(note, strpos(note, $2) + length($2)) FROM _rowvioli.columns__log WHERE id = $1
                      AND strpos(note, $2) > 0 ORDER BY _loaded_at DESC LIMIT 1""", [t["id"], KEYS_NOTE])):
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


# decision 10: what a proof of a rename needs, strict on purpose, since a false one points a consumer's view at another
# column: at least this many rows unchanged otherwise, all equal, with at least this many distinct values
PROOF_ROWS, PROOF_VALUES = 20, 5


def proven(conn, t, mirror, staged, log_columns, renamed):
    """Decision 10: the renames the data prove besides the `renamed` ones, new name to (old name, the note with the
    numbers). A column gone from the mirror and one come that is not in the change log, of one family, compared in one
    query over the rows, joined by the key, whose other columns are unchanged; each must be the other's only proof."""
    had, types, logged = dict(mirror), dict(staged), dict(log_columns)
    gone = [n for n in had if n not in types and n in logged and n not in renamed.values()]
    come = [n for n in types if n not in had and n not in logged and n not in renamed]
    pairs = [(old, new) for old in gone for new in come if family(had[old]) == family(types[new])]
    if not pairs:
        return {}
    moved = {old: new for new, old in renamed.items()}
    on = " AND ".join(f"s.{quote(k)} = m.{quote(moved.get(k, k))}" for k in t["key"])
    other = [n for n in types if n in had and family(had[n]) == family(types[n])]
    unchanged = ("WHERE ROW({}) IS NOT DISTINCT FROM ROW({})".format(
        *(", ".join(f"{a}.{quote(n)}" for n in other) for a in "ms")) if other else "")
    numbers = ", ".join(f"count(*) FILTER (WHERE m.{quote(old)} IS NOT DISTINCT FROM s.{quote(new)}), "
                        f"count(DISTINCT m.{quote(old)})" for old, new in pairs)
    [(rows, *found)] = sql(conn, f"SELECT count(*), {numbers} FROM {t['mirror']} m JOIN _stage s ON {on} {unchanged}")
    proofs = [(old, new, equal, values) for (old, new), equal, values in zip(pairs, found[::2], found[1::2])
              if rows >= PROOF_ROWS and equal == rows and values >= PROOF_VALUES]
    return {new: (old, f"proven by the data: {rows} rows unchanged otherwise, {equal} of them equal, {values} "
                       "distinct values") for old, new, equal, values in proofs
            if [p[0] for p in proofs].count(old) == 1 and [p[1] for p in proofs].count(new) == 1}


# decision 4: the families of types; every other type, without its modifier, is a family of its own
FAMILIES = {"smallint": "exact", "integer": "exact", "bigint": "exact", "numeric": "exact", "real": "float",
            "double precision": "float", "date": "time", "timestamp without time zone": "time"}


def family(type):
    base = re.sub(r"\(.*?\)", "", type)  # numeric(10,2), timestamp(3) without time zone
    return FAMILIES.get(base, base)


def wider(a, b):
    """Decision 5: the type of the family of `a` and `b` that holds the values of both."""
    if a == b:
        return a
    if family(a) in ("float", "time"):
        return {"float": "double precision", "time": "timestamp without time zone"}[family(a)]
    if a in INTEGERS and b in INTEGERS:
        return max(a, b, key=INTEGERS.get)

    def digits(type):  # before and after the point, an integer as many as its largest value; none for plain numeric
        m = re.fullmatch(r"numeric\((\d+),(\d+)\)", type)
        return (INTEGERS[type], 0) if type in INTEGERS else (int(m[1]) - int(m[2]), int(m[2])) if m else None
    if not (digits(a) and digits(b)):
        return "numeric"
    before, after = (max(x, y) for x, y in zip(digits(a), digits(b)))
    return f"numeric({before + after},{after})" if before + after <= 1000 else "numeric"


INTEGERS = {"smallint": 5, "integer": 10, "bigint": 19}


def fit(conn, t, staged, mirror, log_columns, renamed):
    """Decision 5: a staged column of the family of the mirror's or the change log's column keeps that type while every
    value fits it, so that the comparison happens in the target type; where one does not, that column is widened to
    the type that holds both. A renamed column is fitted to its old one. Returns the staged columns with the types
    they are checked and published in, and the widenings as (table, column under its new name, type)."""
    types, had = dict(staged), dict(mirror)
    pairs = [(table, name, into) for table, columns in ((t["mirror"], mirror), (t["log_table"], log_columns))
             for name, type in staged if (into := dict(columns).get(renamed.get(name, name), type)) != type
             and family(into) == family(type)]  # another family is a column that goes and comes, check() plans it
    # only a target that does not hold the staged type already needs the scan
    widened = [(table, name, wider(into, types[name]))
               for table, name, into in misfits(conn, [p for p in pairs if wider(p[2], types[p[1]]) != p[2]])]
    # the staging table is not altered: the target's type applies on insert, where it now changes no value. A column
    # back in its family takes the change log's type (cases A12)
    taken = {name: into for table, name, into in pairs + widened
             if table == t["mirror"] or renamed.get(name, name) not in had}
    return [(name, taken.get(name, type)) for name, type in staged], widened


def misfits(conn, columns):
    """The (table, column, type) of `columns` with a staged value that the type would change, in one scan."""
    if not columns:
        return []
    changed = [f"bool_or({quote(name)}::{type} IS DISTINCT FROM {quote(name)})" for _, name, type in columns]
    try:
        [row] = sql(conn, f"SELECT {', '.join(changed)} FROM _stage")
    except Exception as e:  # a value too large for the type raises instead; column by column finds which
        if getattr(e, "sqlstate", None) != "22003":  # numeric_value_out_of_range
            raise
        return columns if len(columns) == 1 else [c for column in columns for c in misfits(conn, [column])]
    return [c for c, changes in zip(columns, row) if changes]


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
    options.pop("renamed", None)  # the run's, not the connector's (decision 10)
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
    # the mirror's column each reads: one that went under the change log's name for it, a retired one under its new
    # name and never compared with its successor, a renamed one under its old name
    read = {c: c for c in had if c not in plan["gone"]} | {plan["retired"].get(c, c): c for c in plan["gone"]} \
        | plan["renamed"]
    columns = staged + [(plan["retired"].get(c, c), had[c]) for c in plan["gone"]]
    # a new column is null in the mirror once added, and one that went is null in the source, so a row differs only
    # if the other side has a value there
    s = ", ".join(f"s.{quote(c)}" if c in staging else f"NULL::{type}" for c, type in columns)
    m = ", ".join(f"m.{quote(read[c])}" if c in read else f"NULL::{type}" for c, type in columns)
    first = quote(read.get(t["key"][0], t["key"][0]))
    on = " AND ".join(f"s.{quote(k)} = m.{quote(read.get(k, k))}" for k in t["key"])
    if not mirror or plan["key"].get("by") == "definition":  # under another key: every old row goes, every new comes
        old = f"SELECT 'D'::text, {m} FROM {t['mirror']} m UNION ALL " if mirror else ""
        sql(conn, f"CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in columns)}) AS "
                  f"{old}SELECT 'I'::text, {s} FROM _stage s")
    else:
        sql(conn, f"""CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in columns)}) AS
            SELECT 'D'::text AS _op, {m} FROM {t['mirror']} m WHERE NOT EXISTS (SELECT FROM _stage s WHERE {on})
            UNION ALL
            SELECT CASE WHEN m.{first} IS NULL THEN 'I' ELSE 'U' END, {s}
              FROM _stage s LEFT JOIN {t['mirror']} m ON {on}
             WHERE m.{first} IS NULL OR ROW({s}) IS DISTINCT FROM ROW({m})""")
    counts = dict(sql(conn, "SELECT _op, count(*) FROM _diff GROUP BY _op"))
    return {"inserted": counts.get("I", 0), "updated": counts.get("U", 0), "deleted": counts.get("D", 0)}


def publish(conn, t, staged, delivered, mirror, log, rows_read, counts, plan):
    """Step 6, one transaction in the order of decision 14: the plan, new columns, mirror, change log and its view,
    the columns table, loaded_at, attempts and the run's row. Raises, so nothing is published, when the table's row
    no longer gives it this target name."""
    names = ", ".join(quote(c) for c, _ in staged)
    logged = ", ".join(quote(c) for c in [*dict(staged), *(plan["retired"].get(c, c) for c in plan["gone"])])
    new = not mirror
    moved = plan["retired"] | {o: n for n, o in plan["renamed"].items()}  # the names carry_out gives
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
        widen(conn, t["mirror"], staged, [(moved.get(n, n), type) for n, type in mirror if n not in plan["gone"]])
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
        write_log(conn, t, staged, [(moved.get(n, n), type) for n, type in log], logged)
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
    logged = dict(sql(conn, COLUMNS, [t["log_table"]]))
    for new, old in plan["renamed"].items():  # decision 10: before the widening, which names the new column
        for table in (t["mirror"], t["log_table"]) if old in logged else (t["mirror"],):
            sql(conn, f"ALTER TABLE {table} RENAME COLUMN {quote(old)} TO {quote(new)}")
        by = "source" if new in plan["proven"] else "definition"
        changes[old], changes[new] = {"by": by}, {"was": old, "by": by, "note": plan["proven"].get(new)}
    for old, new in plan["retired"].items():
        sql(conn, f"ALTER TABLE {t['log_table']} RENAME COLUMN {quote(old)} TO {quote(new)}")
        changes[new] = {"was": old}
    # decision 9: the comment on _op names the key columns of every stretch, renamed and retired ones by their new names
    moved = plan["retired"] | {o: n for n, o in plan["renamed"].items()}
    if moved and (keys := stretches(conn, t)):
        if (named := [{**k, "key": [moved.get(c, c) for c in k["key"]]} for k in keys]) != keys:
            note = KEYS_NOTE + keys_of_log(conn, t, named)
            for old in {c for k in keys for c in k["key"]} & moved.keys():
                changes[moved[old]]["note"] = "; ".join(filter(None, [changes[moved[old]].get("note"), note]))
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
            [(now,)] = sql(conn, "SELECT to_json(now()) #>> '{}'")  # ISO 8601, whatever the DateStyle
            keys = (stretches(conn, t) or [{"key": was}]) + [{"from": now, "key": key}]
            note = KEYS_NOTE + keys_of_log(conn, t, keys)
        changes.update({c: {**changes.get(c, {}), "by": by, "note": note} for c in {*was, *key}})  # a rename keeps was
    for name in plan["gone"]:
        [(note,)] = sql(conn, DROPS_WITH, [t["mirror"], name])
        changes[name] = {"note": f"{note} went with it" if note else None}
        alter(conn, f"column {name} " + ("has another type in the source" if name in plan["retired"]
                                         else "is gone from the source") + f" and would leave the mirror {t['name']}",
              f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
    for table in (t["mirror"], t["log_table"]):  # decision 5, one ALTER per table, so it is rewritten at most once
        if widened := [(name, type) for into, name, type in plan["widen"] if into == table]:
            columns = ", ".join(f"column {name} to {type}" for name, type in widened)
            say(widening=f"{table}, {columns}")  # the worker names it if it ends the run meanwhile (decision 15)
            alter(conn, f"{table} would be widened for values of the source, {columns}",
                  f"ALTER TABLE {table} " + ", ".join(f"ALTER {quote(n)} TYPE {type}" for n, type in widened))
    return changes


KEYS_NOTE = "the change log's keys: "  # the note in the columns table of a change of key, before the comment's text
# (the reader's versions may come first)


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
        # dependent_objects_still_exist, and feature_not_supported for a type a view's column holds
        if details.get("PG_DIAG_SQLSTATE") not in ("2BP01", "0A000") or "PG_DIAG_MESSAGE_DETAIL" not in details:
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
        widened = follow(conn, t) or widened
        rows = f"SELECT _op, {names} FROM _diff"
    else:
        sql(conn, f"CREATE TABLE {t['log_table']} (_run bigint, _op text, _loaded_at timestamptz, LIKE {t['mirror']})")
        # its one key said, so that a change of key the columns table noted for an earlier change log does not stop it
        keys_of_log(conn, t, [{"key": t["key"]}])
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


def follow(conn, t):
    """Decision 20: a type that a person widened in the mirror is followed in the change log, so that what the mirror
    holds fits it. The history view reads the column, so it goes first and the caller creates it again. Says whether
    it altered one."""
    mirror = dict(sql(conn, COLUMNS, [t["mirror"]]))
    widened = [(name, into) for name, type in sql(conn, COLUMNS, [t["log_table"]])
               if (into := mirror.get(name)) and into != type and family(into) == family(type)
               and wider(type, into) == into]
    if widened:
        sql(conn, "SET LOCAL lock_timeout = '10s'")
        sql(conn, f"DROP VIEW IF EXISTS {t['history']}")
        sql(conn, f"ALTER TABLE {t['log_table']} " + ", ".join(f"ALTER {quote(n)} TYPE {into}" for n, into in widened))
    return bool(widened)


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
    # the primary key's order, not the definition's: the same columns in another order are the same key (story 20)
    key = {k: i + 1 for i, (k,) in enumerate(sql(conn, PRIMARY_KEY, [t["mirror"]]))}
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
        # one the source did not deliver keeps the type it last did, a retired one that of the name it had (story 34)
        last = old.get(changes.get(name, {}).get("was", name), {}).get("source_type", type)
        row = dict(target_schema=t["schema"], target_table=t["table"], column=name, type=type,
                   source_type=delivered.get(name, last), key=key.get(name), mirror=in_mirror, was=None, note=None)
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
    pinned = dict(t["options"].get("columns") or {})  # a type the definition gives (decision 19), stored as pairs
    for r in rows:
        if (r["target_schema"], r["target_table"]) == (t["schema"], t["table"]):
            r.update(changes.get(r["column"], {}))
            # REST's columns are all the definition's, also one taken out of it; a retired one is by its name's cause
            if r["by"] == "source" and (t["type"] == "rest" or r["column"] in pinned or r["was"] in pinned):
                r["by"] = "definition"
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
