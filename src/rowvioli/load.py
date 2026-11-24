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
from datetime import datetime
from urllib.parse import unquote

import pyarrow as pa
import pyarrow.compute as pc

from . import contract, seal, target
from .definition import CONTROL, RESERVED
from .target import CLAIMABLE, literal, quote, sql

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
    """In one transaction under the counting lock (docs/target.md "How Postgres counts"): takes the table lock of a
    claimable table in scope never tried, else of the most overdue, counts the attempt and opens the run's row with
    the hash of the definition. Returns the run's facts, as the definition says at this moment, or None."""
    sql(conn, "BEGIN")
    try:
        sql(conn, "SELECT pg_advisory_xact_lock(0, 0)")
        picked = sql(conn, f"SELECT id, source_id FROM ({CLAIMABLE}) c ORDER BY overdue DESC NULLS FIRST LIMIT 1",
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
    # a dict under columns is stored as pairs (definition.ordered), any other value as written; `pinned` are the types
    # the definition gives, none where a connector of one's own takes another value there
    if isinstance(c := t["options"].get("columns"), list) and all(isinstance(p, list) and len(p) == 2 for p in c):
        t["options"]["columns"] = dict(c)
    t["pinned"] = c if isinstance(c := t["options"].get("columns"), dict) else {}
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
    # decision 54: a connector whose catalog is its data (a file) has no column that goes; one its data lack this run
    # is empty. One a change log lacks, or every one without a change log, is not known to be from the source, and
    # check() stops it rather than empty a person's column. One the definition says is renamed to a column the data
    # have is renamed. REST delivers every column under `columns`, even one no row has: the definition is its catalog,
    # and a column taken out of it goes as one a database drops
    stated = {old for new, old in (t["options"].get("renamed") or {}).items()
              if new in dict(staged) and new not in dict(mirror)}
    if t["catalog"] == "data" and (missing := [(n, type) for n, type in mirror if n not in dict(staged)
                                            and n not in stated and n in dict(log_columns)]):
        sql(conn, "ALTER TABLE _stage " + ", ".join(f"ADD {quote(n)} {type}" for n, type in missing))
        staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    plan = check(conn, t, staged, mirror, log_columns)
    staged, plan["widen"], plan["followed"] = fit(conn, t, staged, mirror, log_columns, plan["renamed"])
    t["step"] = "comparing with the mirror"
    counts = diff(conn, t, staged, mirror, plan) if t["key"] else None
    if mirror:  # under another key the mirror is replaced as a whole, and only its shrinkage counts
        check_delete_share(conn, t, rows_read, None if plan["key"] else counts)
    t["step"] = "publishing"
    return publish(conn, t, staged, delivered, mirror, log_columns, rows_read, counts, plan)


def check(conn, t, staged, mirror, log_columns):
    """Step 4 (docs/loading.md "Checks before publishing") and the plan (decision 54): what the run does to the columns
    besides adding the new ones, which publish adds. Every stop a rule makes is here, before anything is written. The
    plan: `gone`, the mirror's columns that leave it and stay in the change log, `retired`, the change log's columns
    that keep their values under another name as one of another family comes, old name to new, and `key` when the
    mirror's primary key is not the definition's: the primary key it `was`, whether the change is `by` the definition
    or the primary key was changed by hand and is put back, and whether a change `log` exists. `renamed`, new name to
    old, the columns that keep their values and history under another name, and `proven`, the note of each one the
    data proved. `unpinned`, the retired ones whose pin under `columns` was taken out."""
    types, logged, had = dict(staged), dict(log_columns), dict(mirror)
    key = t["key"] or []
    if key:  # first: the change log's own columns are never what a way out below renames
        # the diff, the change log and the history view carry them beside the table's columns
        for name in RESERVED if t["log"] else ["_op"]:
            if name in types:
                freed = "; log = false frees it" if name != "_op" else \
                    "; _op cannot be freed: read the source through a view of it that names that column otherwise"
                raise Exception(f"column {name} is a name of the change log or the history view, so a table with a "
                                f"key cannot have it{freed}")
    way =("rename that column of the change log and drop its history view, which the next run creates again: "
           f"ALTER TABLE {t['log_table']} RENAME COLUMN {{}} TO <another name>; DROP VIEW {t['history']}")
    # decision 54: a rename the definition states acts once its old column is gone and its new one has come
    renamed = {new: old for new, old in (t["options"].get("renamed") or {}).items() if old in had
               and old not in types and new in types and new not in had and (not log_columns or old in logged)}
    for new, old in renamed.items():
        stated = f"column {old} is renamed {new} in the table's definition"
        if family(had[old]) != family(types[new]):
            raise Exception(f"{stated}, but {had[old]} and {types[new]} are types of two families, so their values "
                            f"are not the same: take {new} out of renamed")
        if new in logged:
            raise Exception(f"{stated}, but the change log has a column {new} already: " + way.format(quote(new)))
    # the key after the renames: Postgres renames a column inside the primary key by itself (decision 54)
    moved = {old: new for new, old in renamed.items()}
    primary_key = [moved.get(k, k) for (k,) in sql(conn, PRIMARY_KEY, [t["mirror"]])] if mirror else []
    plan = {"renamed": renamed, "proven": {}, "gone": [], "retired": {}, "key": {}, "unpinned": []}
    # nothing is proven without a catalog, a key or a change log, nor joined by a key of another family, which stops below
    if t["key"] and t["log"] and log_columns and not t["catalog"] \
            and set(primary_key) == set(t["key"]) \
            and all(family(had[renamed.get(k, k)]) == family(types[k]) for k in t["key"]):
        proofs = proven(conn, t, mirror, staged, log_columns, renamed)
        renamed.update({new: old for new, (old, _) in proofs.items()})
        plan["proven"] = {new: note for new, (_, note) in proofs.items()}
    for name, type in mirror:
        if name in renamed.values():
            continue
        # a run adds a column to mirror and change log together, so one only the mirror has is a person's (story 8)
        # a column added to the change log too would leave the mirror with its values, so the copy is the way out
        if t["key"] and t["log"] and log_columns and name not in logged:
            raise Exception(f"column {name} of the mirror is not in the change log, so it is not known to be from the "
                            "source; " + (f"the source brings a column {name}, which a run would write into: "
                                          if name in types else "")
                            + "drop it from the mirror, after copying its values into a table of your own if they are "
                              "to be kept: CREATE TABLE <a table of yours> AS SELECT "
                              f"{', '.join(quote(c) for c in [*t['key'], name])} FROM {t['mirror']}; "
                              f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
        if name not in types:
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"column {name} is missing in the source; without a change log its values are nowhere "
                                f"else, so a person drops it: ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            plan["gone"].append(name)
        elif family(types[name]) != family(type):  # another family goes and comes (decision 54); fit() did the same
            changed = f"column {name} has changed its type from {type} to {types[name]}"
            # where the definition names the columns it is the catalog. CSV, Excel and JSON deliver every other column
            # as text or jsonb, so another family there is a pin taken out; a type the file brings itself can flip
            if t["catalog"] == "data" and name not in t["pinned"]:
                if name in t["own_types"]:
                    raise Exception(f"{changed}; a source without a catalog guesses its types, so pin it under "
                                    "columns in the table's definition; where its pin was taken out, a person drops it "
                                    f"and the next run adds it anew: ALTER TABLE {t['mirror']} DROP COLUMN "
                                    f"{quote(name)}")
                plan["unpinned"].append(name)
            if name in (t["key"] or []):
                raise Exception(f"{changed}, a type of another family in the key, so a row before cannot be told "
                                "from one after: give the table another target_table, which begins a new mirror")
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"{changed}; without a change log its values are nowhere else, so a person drops it "
                                f"and the next run adds it anew: ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            if family(logged[name]) != family(type):  # the mirror's type changed by hand (cases G4)
                raise Exception(f"column {name} of the mirror has the type {type}, of another family than the "
                                f"{types[name]} the source delivers, and a run does not change it back; drop it from "
                                f"the mirror and the next run brings it again: "
                                f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            plan["gone"].append(name)
    said = comments(conn, t)  # decision 54: a retired column is known by its comment, never by its name
    retired = {n: was for n, text in said.items() if (was := retirement(text))}
    for name, type in staged:
        if name not in logged or name in had and name not in plan["gone"]:
            continue
        if name in retired:
            raise Exception(f"column {name} of the source has the name under which the change log keeps the old "
                            f"values of {retired[name]}: " + way.format(quote(name)))
        if family(logged[name]) == family(type):
            continue
        new = f"{name}__{t['run']}"
        if new in logged or new in types:  # by the source too, in this very run
            raise Exception(f"column {name} of the change log is to keep its old values under {new}, a name that is "
                            "taken: a later run keeps them under its own number, nothing is to be done")
        plan["retired"][name] = new
    # named together, so one round of work leads out: a column renamed alike in mirror and change log goes as one gone
    # from the source, and the source's comes anew (a change log's alone left the mirror's, unknown to it, P18)
    if long := {n: new for n, new in plan["retired"].items() if len(new.encode()) > 63}:
        raise Exception(f"the change log is to keep the old values of {' and '.join(long)} under "
                        f"{' and '.join(long.values())}, names longer than 63 bytes, the most Postgres keeps of a "
                        "name: give each the same shorter name in mirror, change log and history view, and the next run lets "
                        "it go as a column gone from the source, in one step: " + "; ".join(
                            f"ALTER {kind} {table} RENAME COLUMN {quote(n)} TO <a shorter name>" for n in long
                            for kind, table in ([("TABLE", t["mirror"])] if n in had else [])
                            + [("TABLE", t["log_table"]), ("VIEW", t["history"])]))
    if mirror:
        if primary_key and not key and log_columns:  # the program does not end a change log
            raise Exception(f"the definition has no key any more, the mirror's primary key is {primary_key}: "
                            "put the key back, or give the table another target_table; to load it without a key, "
                            f"drop the change log {t['name']}__log with its history view "
                            f"(DROP TABLE {t['log_table']} CASCADE) and the mirror")
        if set(primary_key) != set(key):  # the same columns in another order are the same key (story 20)
            # decision 54: the key the last run recorded is the definition's, so a person changed the primary key
            recorded = sql(conn, 'SELECT "column", "key" FROM _rowvioli.columns WHERE id = $1', [t["id"]])
            # without a record (a program that kept none), the comment on _op names the key the change log was
            # written under, which is the definition's where a person changed the primary key
            keys = None if recorded or not log_columns else stretches(conn, t)
            hand = {moved.get(c, c) for c, k in recorded if k is not None} == set(key) if recorded else \
                {moved.get(c, c) for c in keys[-1]["key"]} == set(key) if keys else \
                before_the_record(conn, t, primary_key, key, log_columns, renamed)
            plan["key"] = {"was": primary_key, "by": "hand" if hand else "definition", "log": bool(log_columns)}
    # a change log that exists is complete: a run that would leave it behind its mirror, or lay a new mirror's
    # history over it, fails
    why = ("this run would not write to it (log = false or no key)" if not (key and t["log"])
           else "its mirror is missing" if not mirror else None)
    if log_columns and why:
        raise Exception(f"the change log {t['name']}__log exists and {why}: drop it with its history view "
                        f"(DROP TABLE {t['log_table']} CASCADE), or rename both" + (" with the mirror" if mirror else ""))
    # decision 54: one branch over a change log written under two keys gives wrong rows, so the record says them
    if log_columns and stretches(conn, t) is None and (noted := sql(
            conn, """SELECT substr(note, strpos(note, $2) + length($2)) FROM _rowvioli.columns__log WHERE id = $1
                      AND strpos(note, $2) > 0 ORDER BY _loaded_at DESC LIMIT 1""", [t["id"], KEYS_NOTE])):
        raise Exception(f"the comment on column _op of the change log {t['name']}__log, which says the keys it was "
                        "written under, is missing or unreadable, and the key has changed: put it back, "
                        f"COMMENT ON COLUMN {t['log_table']}._op IS {literal(noted[0][0])}")
    # the same for a retired column's comment, whose text the record noted when the run retired it
    for name, note in sql(conn, 'SELECT "column", note FROM _rowvioli.columns WHERE id = $1 AND target_schema = $2 '
                                "AND target_table = $3 AND NOT mirror AND strpos(note, $4) > 0",
                          [t["id"], t["schema"], t["table"], RETIRED_NOTE]):
        if name in said and name not in retired:
            text = json.dumps(json.JSONDecoder().raw_decode(note.partition(RETIRED_NOTE)[2])[0])
            raise Exception(f"the comment on column {name} of the change log {t['name']}__log, which says that it "
                            f"keeps the old values of {retirement(text)}, is missing or unreadable: put it back, "
                            f"COMMENT ON COLUMN {t['log_table']}.{quote(name)} IS {literal(text)}")
    if key:
        names =", ".join(quote(k) for k in key)
        if sql(conn, f"SELECT 1 FROM _stage WHERE {' OR '.join(quote(k) + ' IS NULL' for k in key)} LIMIT 1"):
            raise Exception(f"a key column of ({names}) is null")
        if sql(conn, f"SELECT 1 FROM _stage GROUP BY {names} HAVING count(*) > 1 LIMIT 1"):
            raise Exception(f"a key combination of ({names}) occurs twice")
    return plan


def before_the_record(conn, t, primary_key, key, log_columns, renamed):
    """Decision 54: whether a person changed the primary key of a mirror the record does not know (a target of 0.4.1,
    which refused every run under a primary key other than the definition's). The table's last successful run loaded
    under the definition's key then, so the same definition now says a person changed it. Otherwise the change log,
    written under one of the two keys, says which: under the other a key value has two rows at one moment, an I while
    it lives or a U or D while it does not. Stops where neither tells: the program never guesses what identifies a
    row (story 22)."""
    [(same,)] = sql(conn, """SELECT definition = (SELECT definition FROM _rowvioli.runs WHERE "table" = r."table"
                                                     AND status = 'ok' ORDER BY run DESC LIMIT 1)
                               FROM _rowvioli.runs r WHERE run = $1""", [t["run"]])
    if same:
        return True
    if not log_columns:  # replaced as a whole and under the definition's key either way, with no history to get wrong
        return False
    defined, primary = ([renamed.get(c, c) for c in k] for k in (key, primary_key))  # the change log's names
    fits = [bool(k) and set(k) <= dict(log_columns).keys() and not sql(conn, f"""
        SELECT 1 FROM (SELECT _op, _loaded_at, lag(_op) OVER w AS before, lag(_loaded_at) OVER w AS at
                       FROM ONLY {t['log_table']} WINDOW w AS (PARTITION BY {', '.join(quote(c) for c in k)}
                                                          ORDER BY _loaded_at)) l
         WHERE at = _loaded_at OR (_op = 'I') <> (before IS NULL OR before = 'D') LIMIT 1""") for k in (defined, primary)]
    if fits[0] != fits[1]:
        return fits[0]
    comment = f"COMMENT ON COLUMN {t['log_table']}._op IS " + "{}"
    raise Exception(f"the primary key of {t['name']} is ({', '.join(primary_key)}), the definition's key is "
                    f"({', '.join(key)}), and nothing in the target tells which of them the change log {t['name']}__log "
                    f"was written under: say it, {comment.format(literal(json.dumps([{'key': defined}])))} where a "
                    "person changed the primary key, which the next run puts back, or "
                    f"{comment.format(literal(json.dumps([{'key': primary}])))} where the definition changed the key")


# decision 54: what a proof of a rename needs, strict on purpose, since a false one points a consumer's view at another
# column: at least this many rows unchanged otherwise, all equal, with at least this many distinct values
PROOF_ROWS, PROOF_VALUES = 20, 5


def proven(conn, t, mirror, staged, log_columns, renamed):
    """Decision 54: the renames the data prove besides the `renamed` ones, new name to (old name, the note with the
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
    [(rows, *found)] = sql(conn, f"SELECT count(*), {numbers} FROM ONLY {t['mirror']} m JOIN _stage s ON {on} "
                                 f"{unchanged}")
    proofs = [(old, new, equal, values) for (old, new), equal, values in zip(pairs, found[::2], found[1::2])
              if rows >= PROOF_ROWS and equal == rows and values >= PROOF_VALUES]
    return {new: (old, f"proven by the data: {rows} rows unchanged otherwise, {equal} of them equal, {values} "
                       "distinct values") for old, new, equal, values in proofs
            if [p[0] for p in proofs].count(old) == 1 and [p[1] for p in proofs].count(new) == 1}


# decision 54: the families of types; every other type, without its modifier, is a family of its own
FAMILIES = {"smallint": "exact", "integer": "exact", "bigint": "exact", "numeric": "exact", "real": "float",
            "double precision": "float", "date": "time", "timestamp without time zone": "time"}


def family(type):
    base = re.sub(r"\(.*?\)", "", type)  # numeric(10,2), timestamp(3) without time zone
    return FAMILIES.get(base, base)


def wider(a, b):
    """Decision 54: the type of the family of `a` and `b` that holds the values of both."""
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
    """Decision 54: a staged column of the family of the mirror's or the change log's column keeps that type while every
    value fits it, so that the comparison happens in the target type; where one does not, that column is widened to
    the type that holds both. A renamed column is fitted to its old one. Returns the staged columns with the types
    they are checked and published in, the widenings as (table, column under its new name, type), and the change
    log's columns among them that follow a type a person widened in the mirror, under the plan's lock."""
    types, had = dict(staged), dict(mirror)
    moved = {old: new for new, old in renamed.items()}
    # not one the source retires: that log column takes another name in this run
    followed = {n: into for n, type in log_columns if (into := had.get(n)) and into != type
                and family(into) == family(type) == family(types.get(moved.get(n, n), into))
                and wider(type, into) == into}
    log_columns = [(n, followed.get(n, type)) for n, type in log_columns]
    pairs = [(table, name, into) for table, columns in ((t["mirror"], mirror), (t["log_table"], log_columns))
             for name, type in staged if (into := dict(columns).get(renamed.get(name, name), type)) != type
             and family(into) == family(type)]  # another family is a column that goes and comes, check() plans it
    # only a target that does not hold the staged type already needs the scan
    widened = [(table, name, wider(into, types[name]))
               for table, name, into in misfits(conn, [p for p in pairs if wider(p[2], types[p[1]]) != p[2]])]
    follow = [(t["log_table"], moved.get(n, n), into) for n, into in followed.items()
              if (t["log_table"], moved.get(n, n)) not in {w[:2] for w in widened}]
    widened += follow
    # the staging table is not altered: the target's type applies on insert, where it now changes no value. A column
    # back in its family takes the change log's type (cases A12)
    taken = {name: into for table, name, into in pairs + widened
             if table == t["mirror"] or renamed.get(name, name) not in had}
    return [(name, taken.get(name, type)) for name, type in staged], widened, [name for _, name, _ in follow]


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
    before = sql(conn, f"SELECT count(*) FROM ONLY {t['mirror']}")[0][0]
    gone = counts["deleted"] if counts else before - rows_read
    if before and gone / before > t["max_delete_share"]:
        raise Exception(f"{round(100 * gone / before)} % of the rows would be deleted, more than max_delete_share = "
                        f"{t['max_delete_share']} allows: the source table may have been replaced or emptied; if so, "
                        "max_delete_share = 1.0 on the table lets one run through")


def stage(conn, t):
    """Opens the connection, calls the connector and fills the TEMP staging table chunk by chunk. Returns the
    number of rows read."""
    connector = contract.connector(t["type"], f" on worker {t['worker']}")
    t["catalog"] = getattr(connector, "catalog", None)  # the source's own, unless the connector says otherwise
    sql(conn, "UPDATE _rowvioli.runs SET driver_version = $2 WHERE run = $1",
        [t["run"], getattr(connector, "driver_version", None)])
    try:
        connection = seal.unseal(os.environ["ROWVIOLI_KEY_FILE"], t["key_id"], t["source"], t["connection"])
    except Exception as e:
        raise Exception(f"the connection of source {t['source']} cannot be decrypted on worker {t['worker']}: {e}")
    # a directory is no secret, and a reason without it is not readable (decision 47)
    t["values"] = connection_values(connection, ("path",) if t["type"] == "file" else ())
    options = dict(t["options"])
    options.pop("renamed", None)  # the run's, not the connector's (decision 54)
    batches = stream(connector.read(connection, t["source_table"], options))
    if batches is None:
        raise Exception("the connector delivered nothing, not even the columns")

    def cut(name):  # Postgres keeps the first 63 bytes of a name, whole characters, and drops the rest (cases A20)
        return name.encode()[:63].decode(errors="ignore")
    if long := [n for n in batches.schema.names if cut(n) != n]:
        twins = [n for n in batches.schema.names if cut(n) == cut(long[0])]
        raise Exception(f"columns {' and '.join(twins)} of the source are equal in their first 63 bytes, the most "
                        "Postgres keeps of a name: give them names in the source that differ there" if twins[1:] else
                        f"column {long[0]} of the source is longer than 63 bytes, the most Postgres keeps of a name: "
                        "give it a shorter name in the source")
    t["own_types"] = {f.name for f in batches.schema if contract.OWN_TYPE.items() <= (f.metadata or {}).items()}
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
        raised = []
        try:
            rows_read = c.adbc_ingest("_stage", without_nul(batches, raised), mode="append", temporary=True)
        except Exception:  # the driver gives what the connector raised in its stream as its own error, cut and wrapped
            if raised:
                raise raised[0] from None
            raise
    # zero rows protect a mirror that has rows; a first load or an empty mirror publishes them
    if rows_read == 0 and t["max_delete_share"] < 1 and sql(conn, "SELECT to_regclass($1)", [t["mirror"]])[0][0] and \
            sql(conn, f"SELECT 1 FROM ONLY {t['mirror']} LIMIT 1"):
        raise Exception("the source delivered zero rows; max_delete_share = 1.0 allows an empty table")
    # json has no equality, so the comparison could not run; the driver writes Arrow's json only as json
    jsonb = {"json": "jsonb", "json[]": "jsonb[]"}
    to_jsonb = [f"ALTER {quote(n)} TYPE {jsonb[type]} USING {quote(n)}::{jsonb[type]}"
                for n, type in sql(conn, COLUMNS, ["pg_temp._stage"]) if type in jsonb]
    if to_jsonb:
        sql(conn, "ALTER TABLE _stage " + ", ".join(to_jsonb))
    return rows_read


def without_nul(batches, raised):
    """Postgres text cannot hold 0x00, so there is no faithful way to keep it: it is removed (decision 51). What the
    connector raises while its batches are read goes to `raised` too."""
    # shortcut: only top-level string columns, a NUL inside a list or struct still fails the run, upgrade when a source needs it
    text = [i for i, f in enumerate(batches.schema) if pa.types.is_string(f.type) or pa.types.is_large_string(f.type)]

    def clean():
        try:
            for b in batches:
                for i in text:
                    b = b.set_column(i, batches.schema.field(i), pc.replace_substring(b.column(i), "\x00", ""))
                yield b
        except Exception as e:
            raised.append(e)
            raise
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
    """Step 5, by the plan (decision 54): the rows that differ into the TEMP table _diff (docs/target.md "Comparing in
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
        old = f"SELECT 'D'::text, {m} FROM ONLY {t['mirror']} m UNION ALL " if mirror else ""
        sql(conn, f"CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in columns)}) AS "
                  f"{old}SELECT 'I'::text, {s} FROM _stage s")
    else:
        sql(conn, f"""CREATE TEMP TABLE _diff (_op, {', '.join(quote(c) for c, _ in columns)}) AS
            SELECT 'D'::text AS _op, {m} FROM ONLY {t['mirror']} m WHERE NOT EXISTS (SELECT FROM _stage s WHERE {on})
            UNION ALL
            SELECT CASE WHEN m.{first} IS NULL THEN 'I' ELSE 'U' END, {s}
              FROM _stage s LEFT JOIN ONLY {t['mirror']} m ON {on}
             WHERE m.{first} IS NULL OR ROW({s}) IS DISTINCT FROM ROW({m})""")
    counts = dict(sql(conn, "SELECT _op, count(*) FROM _diff GROUP BY _op"))
    return {"inserted": counts.get("I", 0), "updated": counts.get("U", 0), "deleted": counts.get("D", 0)}


def publish(conn, t, staged, delivered, mirror, log, rows_read, counts, plan):
    """Step 6, one transaction in the order of decision 54: the plan, new columns, mirror, change log and its view,
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
    elif not new and dict(staged).keys() - {moved.get(n, n) for n, _ in mirror}:
        # added columns alone: mirror, change log and history view are altered one after the other, so a run that waited
        # for one while holding another could deadlock with a consumer reading them (story 43)
        lock(conn, t)
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
            only = f" AND NOT EXISTS (SELECT FROM ONLY {t['mirror']} m WHERE {on})"
        sql(conn, f"DELETE FROM ONLY {t['mirror']} m USING _diff d WHERE d._op IN ('D', 'U') AND {on}{kept}")
        written = rowcount(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _diff d "
                                 f"WHERE _op IN ('I', 'U'){only}")
        # the counts are the mirror's: a U only the change log gets, for a column that went, updates no row of it
        counts = {**counts, "updated": written - counts["inserted"]}
    else:  # without a key, or under another key (decision 54): replaced as a whole
        deleted = rowcount(conn, f"DELETE FROM ONLY {t['mirror']}")
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
    """Decision 54: opens the publishing transaction holding mirror, change log and history view, taken in one
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


# what Postgres drops with a column without a word (decision 54): indexes, constraints, the grants on the column
DROPS_WITH = """
    SELECT concat_ws(', ', (SELECT string_agg(pg_describe_object(classid, objid, 0), ', ' ORDER BY objid) FROM pg_depend
                             WHERE refclassid = 'pg_class'::regclass AND refobjid = a.attrelid
                               AND refobjsubid = a.attnum AND deptype = 'a'),
                           (SELECT string_agg(format('the grant of %s to %s', privilege_type, CASE grantee WHEN 0
                                   THEN 'public' ELSE grantee::regrole::text END), ', ') FROM aclexplode(a.attacl)))
      FROM pg_attribute a WHERE attrelid = $1::regclass AND attname = $2"""


# the grants on a view but its owner's, as (privilege, column or None, grantee, grant option, grantor or None for the
# owner), in the order Postgres keeps them, which gives a grantee its grant option before it passes the grant on
GRANTS = """
    SELECT a.privilege_type, c.attname::text, CASE a.grantee WHEN 0 THEN 'PUBLIC' ELSE a.grantee::regrole::text END,
           a.is_grantable, nullif(a.grantor, r.relowner)::regrole::text
      FROM pg_class r CROSS JOIN LATERAL (SELECT NULL::name AS attname, 0 AS attnum, r.relacl AS acl UNION ALL
                                          SELECT attname, attnum, attacl FROM pg_attribute WHERE attrelid = r.oid) c,
           aclexplode(c.acl) WITH ORDINALITY a WHERE r.oid = to_regclass($1) AND a.grantee <> r.relowner
     ORDER BY c.attnum, a.ordinality"""


def carry_out(conn, t, plan):
    """Decision 54, under the lock: the history view goes, since Postgres alters no column a view reads (write_log
    creates it again and gives its grants again, a renamed column's under its new name), then the plan. Returns what
    the columns table says beyond the catalogue (decision 54)."""
    renamed = {old: new for new, old in plan["renamed"].items()}
    t["grants"] = [(p, renamed.get(c, c), *rest) for p, c, *rest in sql(conn, GRANTS, [t["history"]])]
    alter(conn, t, f"the columns of {t['name']} change", f"DROP VIEW IF EXISTS {t['history']}", t["history"])
    changes = {}
    logged = dict(sql(conn, COLUMNS, [t["log_table"]]))
    keys = stretches(conn, t) if logged else None  # while the columns it names have those names
    for new, old in plan["renamed"].items():  # decision 54: before the widening, which names the new column
        for table in (t["mirror"], t["log_table"]) if old in logged else (t["mirror"],):
            sql(conn, f"ALTER TABLE {table} RENAME COLUMN {quote(old)} TO {quote(new)}")
        by = "source" if new in plan["proven"] else "definition"
        changes[old], changes[new] = {"by": by}, {"was": old, "by": by, "note": plan["proven"].get(new)}
    for old, new in plan["retired"].items():
        sql(conn, f"ALTER TABLE {t['log_table']} RENAME COLUMN {quote(old)} TO {quote(new)}")
        text = json.dumps({"retired": old})  # the change log says it of itself, as of its keys
        sql(conn, f"COMMENT ON COLUMN {t['log_table']}.{quote(new)} IS {literal(text)}")
        changes[new] = {"was": old, "note": RETIRED_NOTE + text}
    # decision 54: the comment on _op names the key columns of every stretch, renamed and retired ones by their new names
    moved = plan["retired"] | {o: n for n, o in plan["renamed"].items()}
    if moved and keys:
        if (named := [{**k, "key": [moved.get(c, c) for c in k["key"]]} for k in keys]) != keys:
            note = KEYS_NOTE + keys_of_log(conn, t, named)
            for old in {c for k in keys for c in k["key"]} & moved.keys():
                changes[moved[old]]["note"] = "; ".join(filter(None, [changes[moved[old]].get("note"), note]))
    if plan["key"]:  # decision 54: publish adds the new primary key once the rows are in
        was, key, by = plan["key"]["was"], t["key"] or [], plan["key"]["by"]
        note = (f"the primary key ({', '.join(was)}) was put back to the definition's ({', '.join(key)})"
                if by == "hand" else None)
        if was:
            [(name,)] = sql(conn, "SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass AND contype = 'p'",
                            [t["mirror"]])
            dropped = alter(conn, t, f"the key of {t['name']} would change from ({', '.join(was)}) to "
                                     f"({', '.join(key)})", f"ALTER TABLE {t['mirror']} DROP CONSTRAINT {quote(name)}",
                            t["mirror"], constraint=name)
        # Postgres leaves NOT NULL behind, also where LIKE copied it; a column still in a key it refuses to free
        if (loose := [c for c in was if c not in key]) and (not was or dropped):
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
        alter(conn, t, f"column {name} " + ("has another type in the source" if name in plan["retired"]
                                         else "is gone from the source") + f" and would leave the mirror {t['name']}",
              f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}", t["mirror"], [name])
    for name in plan["unpinned"]:  # decision 54: a type the definition gave, and took back
        changes[name]["by"] = changes[plan["retired"][name]]["by"] = "definition"
    for table in (t["mirror"], t["log_table"]):  # decision 54, one ALTER per table, so it is rewritten at most once
        if widened := [(name, type) for into, name, type in plan["widen"] if into == table]:
            columns = ", ".join(f"column {name} to {type}" for name, type in widened)
            say(widening=f"{table}, {columns}")  # the worker names it if it ends the run meanwhile (decision 54)
            hand = set(plan["followed"]) if table == t["log_table"] else set()
            why = " and ".join(w for w, some in [("for values of the source", len(widened) > len(hand)),
                                                 ("to follow the mirror, which a person widened", hand)] if some)
            alter(conn, t, f"{table} would be widened {why}, {columns}",
                  f"ALTER TABLE {table} " + ", ".join(f"ALTER {quote(n)} TYPE {type}" for n, type in widened),
                  table, [n for n, _ in widened], drop=False)
    if t.get("blocked"):
        raise Exception("; and ".join(t["blocked"]) + ": change or drop that, and the next run goes on")
    return changes


KEYS_NOTE = "the change log's keys: "  # the note in the columns table of a change of key, before the comment's text
# (the reader's versions may come first)
RETIRED_NOTE = "the change log's comment: "  # the note of a retired column, before its comment's text


def comments(conn, t):
    """Decision 54: what the change log says of itself, the comment on each of its columns by name (None for none):
    on _op its keys, on a retired column whose old values it keeps. Empty without a change log."""
    return dict(sql(conn, "SELECT attname, col_description(attrelid, attnum) FROM pg_attribute WHERE attrelid = "
                          "to_regclass($1) AND attnum > 0 AND NOT attisdropped", [t["log_table"]]))


def retirement(text):
    """The column whose old values a change log's column keeps, as its comment says it, or None."""
    try:
        was = json.loads(text)["retired"]
        return was if isinstance(was, str) else None
    except Exception:  # no comment, or one the program did not write
        return None


def stretches(conn, t):
    """Decision 54: the keys the change log was written under, as the comment on its column _op says them, a list of
    {"key": [...]} with "from", the moment it began, on every one but the first. None without a readable comment, also
    for one that names a column the change log lacks: such a change log has had one key."""
    said = comments(conn, t)
    try:
        keys, names = json.loads(said.get("_op")), list(said)
        if keys and all(isinstance(k["key"], list) and k["key"] and all(c in names for c in k["key"])
                        and ("from" in k) == (i > 0) and (not i or datetime.fromisoformat(k["from"]))
                        for i, k in enumerate(keys)):
            return keys
    except Exception:  # anything but the list it should be: unreadable
        pass
    return None


def keys_of_log(conn, t, keys):
    """Writes `keys` as the comment on the change log's column _op; returns the text."""
    text = json.dumps(keys)
    sql(conn, f"COMMENT ON COLUMN {t['log_table']}._op IS {literal(text)}")
    return text


# what Postgres refuses a change of table $1 for: of its columns $2 (a JSON list), of all of it for none, or of its
# constraint $4; with $5 a drop, else a change of type. A drop is refused for every object that depends on what it drops
# or on what goes with it (the index of a constraint or of a column), a change of type for the views and materialized
# views, rules, triggers, policies, publications and generated columns on the columns, and both for the views on those
# views, layer by layer, as the detail of a DROP says them. Read from the catalogue, which takes no lock on them. The last
# field: the history view $3, whose drop the plan makes and names what is in its way
IN_THE_WAY = """
    WITH RECURSIVE it(classid, objid, objsubid) AS (
        SELECT 'pg_class'::regclass, attrelid, attnum::int FROM pg_attribute
         WHERE attrelid = $1::regclass AND attname IN (SELECT json_array_elements_text($2::json))
        UNION SELECT 'pg_class'::regclass, $1::regclass::oid, 0 WHERE $2::text = '[]' AND $4::text IS NULL
        UNION SELECT 'pg_constraint'::regclass, oid, 0 FROM pg_constraint WHERE conrelid = $1::regclass AND conname = $4
        UNION
        SELECT d.classid, d.objid, 0 FROM it JOIN pg_depend d ON (d.refclassid, d.refobjid) = (it.classid, it.objid)
           AND it.objsubid IN (0, d.refobjsubid) AND d.deptype IN ('a', 'i') AND $5),
    on_it(rel, describe, what) AS (
        SELECT CASE WHEN r.rulename = '_RETURN' THEN r.ev_class END,
               CASE WHEN r.rulename = '_RETURN' THEN pg_describe_object('pg_class'::regclass, r.ev_class, 0)
                    WHEN g.oid IS NOT NULL THEN pg_describe_object('pg_class'::regclass, g.adrelid, g.adnum)
                    ELSE pg_describe_object(d.classid, d.objid, 0) END,
               pg_describe_object(it.classid, it.objid, it.objsubid)
          FROM it JOIN pg_depend d ON (d.refclassid, d.refobjid) = (it.classid, it.objid)
           AND it.objsubid IN (0, d.refobjsubid) AND d.deptype = 'n'
          LEFT JOIN pg_rewrite r ON d.classid = 'pg_rewrite'::regclass AND r.oid = d.objid
          LEFT JOIN pg_attrdef g ON d.classid = 'pg_attrdef'::regclass AND g.oid = d.objid
         WHERE $5 OR d.classid IN ('pg_rewrite'::regclass, 'pg_trigger'::regclass, 'pg_policy'::regclass,
                                   'pg_publication_rel'::regclass, 'pg_attrdef'::regclass)
        UNION
        SELECT CASE WHEN r.rulename = '_RETURN' THEN r.ev_class END,
               CASE WHEN r.rulename = '_RETURN' THEN pg_describe_object('pg_class'::regclass, r.ev_class, 0)
                    ELSE pg_describe_object('pg_rewrite'::regclass, r.oid, 0) END,
               pg_describe_object('pg_class'::regclass, o.rel, 0)
          FROM on_it o JOIN pg_depend d ON d.refclassid = 'pg_class'::regclass AND d.refobjid = o.rel
          JOIN pg_rewrite r ON r.oid = d.objid
         WHERE d.classid = 'pg_rewrite'::regclass AND r.ev_class <> o.rel AND o.rel IS DISTINCT FROM to_regclass($3))
    SELECT describe, what, coalesce(rel = to_regclass($3), false) FROM on_it ORDER BY describe, what"""


def alter(conn, t, why, statement, table, columns=(), constraint=None, drop=True):
    """A change Postgres refuses while a consumer's object depends on it: the reason says what would have changed,
    then Postgres's detail, which names the object (decision 54). Kept in `t["blocked"]` while carry_out goes on, so
    that the stop names every object in the way and one round of work clears it. The change is of `columns` of `table`,
    of all of it for none, or of its `constraint`: a drop, else a change of type, for which Postgres names one object,
    and the catalogue gives all (IN_THE_WAY). Says whether the change was made.
    A drop locks what depends on what it drops before it refuses: a consumer who reads such a view while the run holds
    the mirror waits for the run, so the run does not wait for the view, which would be a deadlock (story 43); the
    catalogue names it then. Every object is named with its schema, also one on the search path."""
    sql(conn, "SET LOCAL search_path = ''")  # before the savepoint, whose rollback would undo it
    sql(conn, "SAVEPOINT alter")
    sql(conn, "SET LOCAL lock_timeout = '50ms'")  # far below the second after which Postgres looks for a deadlock
    try:
        sql(conn, statement)
        done = True
    except Exception as e:
        details = {k.decode(): v.decode() for k, v in getattr(e, "details", None) or []}
        state = details.get("PG_DIAG_SQLSTATE")
        # dependent_objects_still_exist, feature_not_supported for a type a view's column holds, lock_not_available
        if state not in ("2BP01", "0A000", "55P03") or state != "55P03" and "PG_DIAG_MESSAGE_DETAIL" not in details:
            raise
        sql(conn, "ROLLBACK TO SAVEPOINT alter")
        done = False
        found = sql(conn, IN_THE_WAY, [table, json.dumps(columns), t["history"], constraint, drop]) \
            if state == "55P03" or not drop else []
        named = "; ".join(f"{d} depends on {w}" for d, w, history in found if not history)
        if state == "55P03":
            t.setdefault("blocked", []).append(f"{why}, but {named}, in use, so the run did not wait for it" if named
                                               else f"{why}, but an object that depends on it was in use, so "
                                                    "Postgres did not name it; the next run does")
        elif named or not found:  # else only the history view, whose drop is stopped already with what is in its way
            detail = named or details["PG_DIAG_MESSAGE_DETAIL"].replace("\n", "; ")
            t.setdefault("blocked", []).append(f"{why}, but {detail}")
    sql(conn, "SET LOCAL lock_timeout TO DEFAULT")
    sql(conn, "SET LOCAL search_path TO DEFAULT")
    return done


def write_log(conn, t, staged, log, names):
    """After the mirror is published, in the same transaction: a log that exists gets the diff, a new one begins
    with the whole mirror, so that replaying a log from the last change of key always gives the mirror. The history
    view is created when missing and replaced when the log got a column; otherwise it is not touched, so takes no
    lock."""
    if log:
        widened = widen(conn, t["log_table"], staged, log)
        rows = f"SELECT _op, {names} FROM _diff"
    else:
        sql(conn, f"CREATE TABLE {t['log_table']} (_run bigint, _op text, _loaded_at timestamptz, LIKE {t['mirror']})")
        # its one key said, so that a change of key the columns table noted for an earlier change log does not stop it
        keys_of_log(conn, t, [{"key": t["key"]}])
        rows = f"SELECT 'I', {names} FROM ONLY {t['mirror']}"
    # now() is the transaction's moment, the one that goes into tables.loaded_at
    sql(conn, f"INSERT INTO {t['log_table']} (_run, _loaded_at, _op, {names}) SELECT $1, now(), * FROM ({rows}) r",
        [t["run"]])
    if log and not widened and sql(conn, "SELECT to_regclass($1) IS NOT NULL", [t["history"]])[0][0]:
        return
    columns = ", ".join(quote(c) for c, _ in sql(conn, COLUMNS, [t["log_table"]])
                        if c not in ("_run", "_op", "_loaded_at"))
    # decision 54: a branch per key, over its stretch of the change log: from its I rows at the moment it began, up to
    # the D rows at the moment the next began
    keys = stretches(conn, t) or [{"key": t["key"]}]
    moments = [f"{literal(k['from'])}::timestamptz" for k in keys[1:]]
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
              FROM ONLY {t['log_table']}{' WHERE ' + ' AND '.join(cut) if cut else ''}) h
         WHERE _op <> 'D'""")
    sql(conn, f"CREATE OR REPLACE VIEW {t['history']} AS" + "\n        UNION ALL".join(branches))
    for privilege, column, grantee, option, grantor in t.pop("grants", []):  # those carry_out found before the drop
        # decision 54: a grant a grantee passed on comes back from it, given as that role; Postgres 14 to 17 take no
        # other grantor than the current role (GRANTED BY). Where the run's role may not act as it, the grant is its own
        if grantor:
            sql(conn, "SAVEPOINT grantor")
            try:
                sql(conn, f"SET LOCAL ROLE {grantor}")
            except Exception as e:
                if getattr(e, "sqlstate", None) != "42501":  # insufficient_privilege
                    raise
                sql(conn, "ROLLBACK TO SAVEPOINT grantor")
                grantor = None
        sql(conn, f"GRANT {privilege}{f' ({quote(column)})' if column else ''} ON {t['history']} TO {grantee}"
                  + (" WITH GRANT OPTION" if option else ""))
        if grantor:
            sql(conn, "RESET ROLE")


def record_columns(conn, t, delivered, mirror, log, changes):
    """Decision 54, last in publishing, in its transaction: what the columns of mirror and change log are now
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
            # a first fill finds what is there; what this run changed in a mirror it found has its cause (story 45)
            untouched = not mirror or found.get(name) == (type, in_mirror) and name not in changes
            row.update(op="I", by=("found" if untouched else "source") if not old
                       else "source" if name not in found else "hand")
        else:
            hand = found.get(name) != (before["type"], before["mirror"]) \
                or changes.get(name, {}).get("by") == "hand"  # a primary key put back: the record knew the key
            if not hand and all(before[f] == row[f] for f in ("type", "source_type", "key", "mirror")):
                continue
            row.update(op="U", by="hand" if hand else "source", was=before["was"])
        rows.append(row)
    if not rows:
        return
    pinned = t["pinned"]  # a type the definition gives (decision 54)
    for r in rows:
        if (r["target_schema"], r["target_table"]) == (t["schema"], t["table"]):
            r.update(changes.get(r["column"], {}))
            # REST's columns are all the definition's, also one taken out of it; a retired one is by its name's cause
            if r["by"] == "source" and (t["catalog"] == "definition" or r["column"] in pinned or r["was"] in pinned):
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
    payload = json.dumps(rows)
    fields = 'target_schema, target_table, "column", type, source_type, "key", mirror, was, "by", note'
    sql(conn, f"INSERT INTO _rowvioli.columns__log SELECT $2::bigint, op, now(), {fields}, $3::int FROM {x}",
        [payload, t["run"], t["id"]])
    sql(conn, f"""DELETE FROM _rowvioli.columns c USING {x} WHERE x.op = 'D'
                     AND (c.target_schema, c.target_table, c."column") = (x.target_schema, x.target_table, x."column")""",
        [payload])
    sql(conn, f"""INSERT INTO _rowvioli.columns SELECT {fields}, $2::int FROM {x} WHERE op <> 'D'
                  ON CONFLICT (target_schema, target_table, "column") DO UPDATE SET type = excluded.type,
                  source_type = excluded.source_type, "key" = excluded."key", mirror = excluded.mirror,
                  was = excluded.was, "by" = excluded."by", note = excluded.note, id = excluded.id""",
        [payload, t["id"]])
    if any(r["by"] != "found" for r in rows):
        sql(conn, "SELECT pg_notify('rowvioli_schema', json_build_object('schema', $1::text, 'table', $2::text,"
                  " 'run', $3::bigint)::text)", [t["schema"], t["table"], t["run"]])


def widen(conn, table, staged, existing):
    """Decision 17: adds the source's columns the table lacks, under the lock publish took first (story 43); the
    lock_timeout bounds a wait that lock leaves none for. Says whether it added one."""
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
# the statement (its SQL may hold quotes and lines); a source's error while its rows are read
WRAPPER = re.compile(r"^(?:[A-Z_]+: )?(?:\[libpq\] )?(?:Execution error \[PGRES_[A-Z_]+\]: )?"
                     r"(?:nanoarrow call failed: )?(?:[A-Za-z]+\(.*?\) = \(\d+\) [^.]*\. [A-Za-z ]+: )?"
                     r"(?:Failed to (?:prepare query|execute query(?: '.*?')?|execute prepared statement): )?"
                     r"(?:PGRES_[A-Z_]+ )?(?:ERROR:\s+)?", re.S)


# a row's value Postgres quotes in a message: last, after a colon (`invalid input syntax for type integer: "abc"`), or
# before `is out of range` (`value "…"` for an integer, bare for a float). Names are quoted too, but never there
VALUE = re.compile(r'(?<=: )"[^\n]*"$|(?:^|(?<=\s))"[^\n]*"(?= is out of range)')
OWN = os.path.dirname(os.path.abspath(__file__)) + os.sep  # the program's code, its shipped connectors among it


def reason_line(values, e, step):
    """The reason as it is stored, shown and logged: the first line of the driver's message without its wrapper,
    joined with the next when it ends in a colon, without a value of a row (VALUE), scrubbed last, so that a password
    that occurs in the wrapper (`x`, `query`) does not keep the wrapper from being cut. A message that holds a
    traceback gives the text before it, or the exception's own line (the traceback's last) when nothing is before it;
    ADBC cuts long messages, so the end may be missing. A line saying so, with the exception's type, when there is no
    message. A message raised under a consumer's code is withheld (raised_by_a_consumer)."""
    if withheld := raised_by_a_consumer(e, step):
        return scrub(values, CONTROL.sub("?", withheld))
    # first only a value with a line break or another control character, which the cut and the ? would break up
    text = scrub([v for v in values if v and CONTROL.search(v)], str(e)).strip()
    raised = e.__traceback__
    while raised and raised.tb_next:
        raised = raised.tb_next
    # the program's own reason is one line: a name in it may hold a control character. A plain Exception raised
    # elsewhere, by a connector of one's own, is cut as a driver's message is, since its next lines may quote a row
    if type(e) is Exception and raised and os.path.abspath(raised.tb_frame.f_code.co_filename).startswith(OWN):
        text = CONTROL.sub("?", text)
    before, _, traceback = text.partition("Traceback (most recent call last)")
    before = re.sub(r"\s*Detail: Python exception:\s*$", "", before)
    first, *rest = (WRAPPER.sub("", before).strip() or traceback.strip().split("\n")[-1]).split("\n")
    line = f"{first} {rest[0].strip()}" if first.endswith(":") and rest else first
    line = VALUE.sub('"***"', line).strip()
    if step != "reading the source":  # a source may have a table of that name
        line = re.sub(r"permission denied for table (columns(?:__log)?)$", r"\g<0>: the worker's role lacks a right on "
                      r"_rowvioli.\1, which rowvioli init printed with the upgrade to version 4 "
                      '(docs/operation.md "The target")', line)
    return scrub(values, line) or f"the driver gave no message while {step} ({type(e).__name__})"


# a frame of a function in the context Postgres gives an error, in every language that names its frames:
# `PL/pgSQL function guard() line 3 at RAISE`, `SQL function "f" statement 1`, `PL/Python function "guard"`
FRAME = re.compile(r'(?:PL/\w+|SQL) (?:function|procedure) ("(?:[^"]|"")*"|(?:"[^"]*"|[^\s(])+\(.*?\))')
# Postgres's own messages of a violated constraint, which show names and no value, also raised under a function
CONSTRAINT = re.compile(r'duplicate key value violates unique constraint "[^"]*"'
                        r'|(?:insert or update|update or delete) on table "[^"]*" violates foreign key constraint '
                        r'"[^"]*"(?: on table "[^"]*")?'
                        r'|null value in column "[^"]*" of relation "[^"]*" violates not-null constraint'
                        r'|new row for relation "[^"]*" violates check constraint "[^"]*"'
                        r'|conflicting key value violates exclusion constraint "[^"]*"')


# the classes of SQLSTATE whose messages Postgres writes with names and no value of a row, and which an operator needs
# while publishing: a lost connection, a feature, a transaction's state, a dependent object, a deadlock, a missing right
# or object, resources such as a full disk, a limit, an object in use, a cancel, a system error. A constraint's message
# (class 23) is known by its words (CONSTRAINT)
NAMES = {"08", "0A", "25", "2B", "40", "42", "53", "54", "55", "57", "58"}


def raised_by_a_consumer(e, step):
    """Decision 54, a reason never shows a value: the reason for an error raised under a consumer's code, a trigger on
    the target, a constraint's or a column's function, a function a source view calls, whose message is free text
    that may hold a row (`raise exception 'bad row %', NEW`, `relation "Anna" does not exist` of an EXECUTE), or None
    for any other. Told by a function's frame in the context the driver gives, in its fields for a statement and in its
    text for a source's rows, whatever the function's language, and by the SQLSTATE only RAISE and ASSERT give;
    Postgres's own messages of a violated constraint keep their names. While publishing, an error of the target outside
    the classes of NAMES is withheld too: a function in C or in a language that names no frame (a consumer's trigger,
    constraint or column) gives no other sign, and Postgres's own message of a value (`date field value out of range:
    2000-13-01`) can hold a row's."""
    details = {k.decode(): v.decode(errors="replace") for k, v in getattr(e, "details", None) or []}
    state = details.get("PG_DIAG_SQLSTATE")
    text = str(e)
    function = FRAME.search(details.get("PG_DIAG_CONTEXT") or text.partition("\nCONTEXT:  ")[2])
    message = details.get("PG_DIAG_MESSAGE_PRIMARY") or WRAPPER.sub("", text).split("\n")[0]
    raised = state in ("P0001", "P0004")  # raise_exception, assert
    if not (function or raised or step == "publishing" and state and state[:2] not in NAMES) \
            or CONSTRAINT.fullmatch(message):
        return None
    where = "source" if step == "reading the source" else "target"
    return (f"{f'function {function[1]}' if function else 'a function' if raised else 'a statement'} raised an error"
            f"{f' (SQLSTATE {state})' if state else ''} in the {where}; its message may hold a row's values, so it is "
            f"left out here: the {where}'s server log has it")


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
    conn = target.connect(pooler=False)  # the worker that started this process checked for a pooler
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
