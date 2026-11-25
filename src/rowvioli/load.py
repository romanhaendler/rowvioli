"""One run, in a process of its own (docs/loading.md "A run"): claim, stage, diff, publish, or fail.

Started by the worker loop as `python -m rowvioli.load <worker> <source> <table>`, with a pipe on stdin that
ends with the worker. It tells the worker on stdout,
one JSON object per line: {"claimed": <target table>, "run", "max_seconds"} right after the claim, before reading,
{"long": <what>} before a step of a change that may outlast max_seconds and {"long": null} after it, and
{"table": <target table>, "status", ...counts or "reason"} at the end. It prints nothing if it claimed nothing.
"""
import contextlib
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
    had, logged = dict(mirror), dict(log_columns)
    renamed = acting(t["options"].get("renamed"), had, dict(staged), logged)
    if t["catalog"] == "data" and (missing := [(n, type) for n, type in mirror if n not in dict(staged)
                                            and n not in renamed.values() and n in logged]):
        sql(conn, "ALTER TABLE _stage " + ", ".join(f"ADD {quote(n)} {type}" for n, type in missing))
        staged = sql(conn, COLUMNS, ["pg_temp._stage"])
    plan = check(conn, t, staged, mirror, log_columns, renamed)
    staged, plan["widen"], plan["followed"] = fit(conn, t, staged, mirror, log_columns, plan["renamed"])
    t["step"] = "comparing with the mirror"
    # decision 54: the steps that write a row per row, named to the worker in case they outlast max_seconds
    replaced = plan["key"].get("by") == "definition"
    t["long"] = (f"replacing {t['name']} under the key ({', '.join(t['key'] or [])})"
                 + (", with a D and an I in the change log for every row" if plan["key"]["log"] else "")
                 + "; raise max_seconds once, until a run has replaced it" if replaced else
                 f"writing a row of the change log for every row of {t['name']} that had a value in "
                 f"{' and '.join(plan['gone'])}; raise max_seconds once, until a run has written them"
                 if plan["gone"] else None)
    with long(t["long"]):
        counts = diff(conn, t, staged, mirror, plan) if t["key"] else None
    if mirror:  # under another key the mirror is replaced as a whole, and only its shrinkage counts
        check_delete_share(conn, t, rows_read, None if plan["key"] else counts)
    t["step"] = "publishing"
    t["tries"] = time.monotonic() + 10  # decision 54: lock() and every wait after it, for up to ten seconds
    while True:
        t["locked"], t["blocked"] = False, []
        try:
            return publish(conn, t, staged, delivered, mirror, log_columns, rows_read, counts, plan)
        except Exception as e:  # lock() bounds every wait after it at 50 ms: the run lets go of all and tries again
            if not (t["locked"] and getattr(e, "sqlstate", None) == "55P03"):  # lock_not_available
                raise
            sql(conn, "ROLLBACK")
            if time.monotonic() > t["tries"]:
                raise Exception(f"{t['name']}, its change log and its history view were held by this run when an "
                                "object it needed was in use (such as a table with a foreign key to it, or its row in "
                                "_rowvioli.tables while apply ran), and it stayed in use for 10 s of tries, so the run "
                                "did not wait for it: nothing was published, the next run tries again") from None
            time.sleep(0.1)


def acting(stated, had, delivered, logged):
    """Decision 54: the renames of `stated`, new name to old, that act: the old column is gone from what the source
    delivered and the new one has come."""
    return {new: old for new, old in (stated or {}).items() if old in had and old not in delivered
            and new in delivered and new not in had and (not logged or old in logged)}


def check(conn, t, staged, mirror, log_columns, renamed):
    """Step 4 (docs/loading.md "Checks before publishing") and the plan (decision 54): what the run does to the columns
    besides adding the new ones, which publish adds. Every stop a rule makes is here, before anything is written. The
    plan: `gone`, the mirror's columns that leave it and stay in the change log, `retired`, the change log's columns
    that keep their values under another name as one of another family comes, old name to new, and `key` when the
    mirror's primary key is not the definition's: the primary key it `was`, whether the change is `by` the definition
    or the primary key was changed by hand and is put back, and whether a change `log` exists. `renamed`, new name to
    old, the columns that keep their values and history under another name, the stated ones given and the proven ones
    added, and `proven`, the note of each one the data proved. `unpinned`, the retired ones whose pin under `columns` was taken out. `moved`, the names the retired
    and renamed columns have after the run, old name to new."""
    types, logged, had = dict(staged), dict(log_columns), dict(mirror)
    # first: a table or view of a person's under the name of the change log or the history view is never taken for it.
    # The change log's always, since one of the program's stops a run that would not write it (below)
    names = [(f"{t['name']}__log", "change log", "r", ("_run", "_op", "_loaded_at"))]
    if t["key"] and t["log"]:  # the history view's only where the run has one: 0.4.1 loaded beside a person's
        names.append((f"{t['name']}__history", "history view", "v", ("_valid_from", "_valid_to")))
    for name, what, kind, own in names:
        quoted = t["log_table"] if what == "change log" else t["history"]
        found = sql(conn, "SELECT relkind FROM pg_class WHERE oid = to_regclass($1)", [quoted])
        if found and (found[0][0] != kind or not set(own) <= dict(sql(conn, COLUMNS, [quoted])).keys()):
            raise Exception(f"{name} is not rowvioli's {what} (a {'table' if kind == 'r' else 'view'} with the columns "
                            f"{', '.join(own[:-1])} and {own[-1]}), so the run leaves it alone: rename it, or give the "
                            "table another target_table")
    key = t["key"] or []
    if key:  # the change log's own columns are never what a way out below renames
        # the diff, the change log and the history view carry them beside the table's columns
        for name in RESERVED if t["log"] else ["_op"]:
            if name in types:
                freed = "; log = false frees it" if name != "_op" else \
                    "; _op cannot be freed: read the source through a view of it that names that column otherwise"
                raise Exception(f"column {name} is a name of the change log or the history view, so a table with a "
                                f"key cannot have it{freed}")
    way = ("rename that column of the change log and drop its history view, which the next run creates again: "
            f"ALTER TABLE {t['log_table']} RENAME COLUMN {{}} TO <another name>; DROP VIEW {t['history']}")
    for new, old in renamed.items():  # the renames the definition states that act in this run (load)
        stated = f"column {old} is renamed {new} in the table's definition"
        if family(had[old]) != family(types[new]):
            raise Exception(f"{stated}, but {had[old]} and {types[new]} are types of two families, so their values "
                            f"are not the same: take {new} out of renamed")
        if new in logged:
            raise Exception(f"{stated}, but the change log has a column {new} already: " + way.format(quote(new)))
    # the key after the renames: Postgres renames a column inside the primary key by itself (decision 54)
    renamed_to = {old: new for new, old in renamed.items()}
    primary_key = [renamed_to.get(k, k) for (k,) in sql(conn, PRIMARY_KEY, [t["mirror"]])] if mirror else []
    plan = {"renamed": renamed, "proven": {}, "gone": [], "retired": {}, "key": {}, "unpinned": []}
    # a change log that exists is complete, and the program never ends one: a run that would leave it behind its mirror,
    # or lay a new mirror's history over it, fails, before a column or the key is looked at
    if log_columns and not (key and t["log"] and mirror):
        why = ("this run would not write to it (log = false or no key)" if not (key and t["log"])
               else "its mirror is missing")
        # without it, a column the source no longer has in its family stops with its drop: said here, so one round leads out
        drops = "; ".join(f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(n)}" for n, type in mirror
                          if n not in renamed.values() and (n not in types or family(types[n]) != family(type)))
        raise Exception(f"the change log {t['name']}__log exists and {why}: drop it with its history view "
                        f"(DROP TABLE {t['log_table']} CASCADE)"
                        + (f", and with it the columns of the mirror the source no longer has, whose values are "
                           f"nowhere else then ({drops})" if drops else "")
                        + ", or rename both" + (" with the mirror" if mirror else ""))
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
        # the mirror's type changed by hand (cases G4), whatever the source delivers (ticket 17, M4)
        if name in logged and family(logged[name]) != family(type):
            raise Exception(f"column {name} of the mirror has the type {type}, of another family than the "
                            f"{logged[name]} it has in the change log, and a run does not change it back; drop it from "
                            f"the mirror and the next run brings it again: "
                            f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
        if name not in types:
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"column {name} is missing in the source, and no change log keeps its values, so a "
                                f"person drops it: ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            plan["gone"].append(name)
        elif family(types[name]) != family(type):  # another family goes and comes (decision 54)
            changed = f"column {name} has changed its type from {type} to {types[name]}"
            if name in (t["key"] or []):  # first: a drop would take the key column for good
                raise Exception(f"{changed}, a type of another family in the key, so a row before cannot be told "
                                "from one after: give the table another target_table, which begins a new mirror")
            # where the definition names the columns it is the catalog. CSV, Excel and JSON deliver every other column
            # as text or jsonb, so another family there is a pin taken out; a type the file brings itself can flip
            if t["catalog"] == "data" and name not in t["pinned"]:
                if name in t["own_types"]:
                    raise Exception(f"{changed}; a source without a catalog guesses its types, so pin it under "
                                    "columns in the table's definition; where its pin was taken out, a person drops it "
                                    f"and the next run adds it anew: ALTER TABLE {t['mirror']} DROP COLUMN "
                                    f"{quote(name)}")
                plan["unpinned"].append(name)
            if not (t["key"] and t["log"] and log_columns):
                raise Exception(f"{changed}, and no change log keeps its values, so a person drops it "
                                f"and the next run adds it anew: ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}")
            plan["gone"].append(name)
    # a column the last run recorded in the mirror that a person dropped from it: its last values are closed in the
    # change log, as for a column that goes, and what the source delivers comes as a column that comes back (tickets
    # 17, M3, and 18). Without a record (a table last loaded before version 4) every column the change log has and the
    # mirror lacks, in this one run: write_log closes only a value still current
    if t["key"] and t["log"] and log_columns:
        recorded = sql(conn, 'SELECT "column", mirror FROM _rowvioli.columns WHERE id = $1 AND target_schema = $2 AND '
                             "target_table = $3", [t["id"], t["schema"], t["table"]])
        plan["closed"] = [n for n, in_mirror in recorded or [(n, True) for n in logged if n not in ("_run", "_op", "_loaded_at")]
                          if in_mirror and n in logged and n not in had]
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
    if overlong := {n: new for n, new in plan["retired"].items() if len(new.encode()) > 63}:
        raise Exception(f"the change log is to keep the old values of {' and '.join(overlong)} under "
                        f"{' and '.join(overlong.values())}, names longer than 63 bytes, the most Postgres keeps of a "
                        "name: give each the same shorter name in mirror, change log and history view, and the next run lets "
                        "it go as a column gone from the source, in one step: " + "; ".join(
                            f"ALTER {kind} {table} RENAME COLUMN {quote(n)} TO <a shorter name>" for n in overlong
                            for kind, table in ([("TABLE", t["mirror"])] if n in had else [])
                            + [("TABLE", t["log_table"]), ("VIEW", t["history"])]))
    if mirror:
        # decision 54: the key the last run recorded (this target name's: an old one that stays keeps the key it had)
        recorded = sql(conn, 'SELECT "column", "key" FROM _rowvioli.columns WHERE id = $1 AND target_schema = $2 '
                             'AND target_table = $3 ORDER BY "key"', [t["id"], t["schema"], t["table"]])
        was = [renamed_to.get(c, c) for c, k in recorded if k is not None]
        if set(primary_key) != set(key):  # the same columns in another order are the same key (story 20)
            # the key the last run recorded is the definition's, so a person changed the primary key
            # without a record (a program that kept none), the comment on _op names the key the change log was
            # written under, which is the definition's where a person changed the primary key
            keys = None if recorded or not log_columns else stretches(conn, t)
            hand = {renamed_to.get(c, c) for c, k in recorded if k is not None} == set(key) if recorded else \
                {renamed_to.get(c, c) for c in keys[-1]["key"]} == set(key) if keys else \
                before_the_record(conn, t, primary_key, key, log_columns, renamed)
            plan["key"] = {"was": primary_key, "by": "hand" if hand else "definition", "log": bool(log_columns)}
        elif log_columns and was and set(was) != set(key):
            # a person changed the primary key by hand to the definition's new key before a run did: the change log is
            # written under the recorded one, so the run changes the key as the definition would (ticket 18)
            plan["key"] = {"was": was, "by": "definition", "log": True}
        # the diff joins the mirror by the definition's key, unless it replaces it: a key column it lacks went by hand
        if plan["key"].get("by") != "definition" and (lost := [k for k in key if renamed.get(k, k) not in had]):
            raise Exception(f"key column {' and '.join(lost)} is missing in the mirror {t['name']}, dropped by hand, so "
                            "its rows cannot be told apart: give the table another target_table, which begins a new "
                            "mirror")
    # decision 54: one branch over a change log written under two keys gives wrong rows, so the record says them
    if log_columns and stretches(conn, t) is None and (text := noted(conn, t)):
        raise Exception(f"the comment on column _op of the change log {t['name']}__log, which says the keys it was "
                        "written under, is missing or unreadable, and the key has changed: put it back, "
                        f"COMMENT ON COLUMN {t['log_table']}._op IS {literal(text)}")
    # and one that names another key last than the one the change log is written under, before this run's renames
    last = [renamed.get(c, c) for c in (plan["key"]["was"] if plan["key"].get("by") == "definition" else key)]
    if log_columns and last and (keys := stretches(conn, t)) and set(keys[-1]["key"]) != set(last):
        raise Exception(f"the comment on column _op of the change log {t['name']}__log, which says the keys it was "
                        f"written under, names ({', '.join(keys[-1]['key'])}) last, where the change log is written "
                        f"under ({', '.join(last)}): the comment was changed, or the mirror's primary key was changed "
                        "by hand to the definition's new key before a run changed it; put it back, COMMENT ON COLUMN "
                        f"{t['log_table']}._op IS "
                        + literal(noted(conn, t) or json.dumps([{"key": last}])))
    # the same for a retired column's comment, whose text the record noted when the run retired it
    for name, note in sql(conn, 'SELECT "column", note FROM _rowvioli.columns WHERE id = $1 AND NOT mirror '
                                "AND strpos(note, $2) > 0", [t["id"], RETIRED_NOTE]):  # also under an old target name
        if name in said and name not in retired:
            text = retired_comment(note)
            raise Exception(f"the comment on column {name} of the change log {t['name']}__log, which says that it "
                            f"keeps the old values of {retirement(text)}, is missing or unreadable: put it back, "
                            f"COMMENT ON COLUMN {t['log_table']}.{quote(name)} IS {literal(text)}")
    if key:
        names = ", ".join(quote(k) for k in key)
        if sql(conn, f"SELECT 1 FROM _stage WHERE {' OR '.join(quote(k) + ' IS NULL' for k in key)} LIMIT 1"):
            # a source without a catalog delivers a field its data lack, or name otherwise, as null
            missing = " or missing from its data, where it may be named otherwise, also in case" if t["catalog"] else ""
            raise Exception(f"a key column of ({names}) is null in a row of the source{missing}: give it a value there, "
                            "or give the table a key whose columns always have one")
        if sql(conn, f"SELECT 1 FROM _stage GROUP BY {names} HAVING count(*) > 1 LIMIT 1"):
            raise Exception(f"a key combination of ({names}) occurs twice in the source: make it unique there, or give "
                            "the table a key that identifies a row")
    plan["moved"] = plan["retired"] | {old: new for new, old in renamed.items()}  # the names carry_out gives
    return plan


def noted(conn, t):
    """The latest text of the comment on _op the columns log noted for the table, under any of its target names (a
    mirror renamed by hand), or None. Only a note of this change log counts, one no older than its first row: a change
    log created again, or one of an earlier target name, may have had other stretches (ticket 17)."""
    found = sql(conn, """SELECT substr(note, strpos(note, $2) + length($2)), _loaded_at FROM _rowvioli.columns__log
                          WHERE id = $1 AND strpos(note, $2) > 0 ORDER BY _loaded_at DESC LIMIT 1""",
                [t["id"], KEYS_NOTE])
    # the oldest rows come first in a change log that is only appended to, so EXISTS ends at once where one counts
    if found and sql(conn, f"SELECT EXISTS (SELECT FROM ONLY {t['log_table']} WHERE _loaded_at <= $1)",
                     [found[0][1]])[0][0]:
        return found[0][0]


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
    with long(f"reading the change log {t['name']}__log under the definition's key and the primary key, to tell which "
              "of them wrote it; raise max_seconds once, until a run has told it"):  # 0.6 s per million rows
        fits = [bool(k) and set(k) <= dict(log_columns).keys() and not sql(conn, f"""
            SELECT 1 FROM (SELECT _op, _loaded_at, lag(_op) OVER w AS before, lag(_loaded_at) OVER w AS at
                           FROM ONLY {t['log_table']} WINDOW w AS (PARTITION BY {', '.join(quote(c) for c in k)}
                                                              ORDER BY _loaded_at)) l
             WHERE at = _loaded_at OR (_op = 'I') <> (before IS NULL OR before = 'D') LIMIT 1""")
                for k in (defined, primary)]
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
    renamed_to = {old: new for new, old in renamed.items()}
    on = " AND ".join(f"s.{quote(k)} = m.{quote(renamed_to.get(k, k))}" for k in t["key"])
    other = [n for n in types if n in had and family(had[n]) == family(types[n])]
    unchanged = ("WHERE ROW({}) IS NOT DISTINCT FROM ROW({})".format(
        *(", ".join(f"{a}.{quote(n)}" for n in other) for a in "ms")) if other else "")
    numbers = ", ".join(f"count(*) FILTER (WHERE m.{quote(old)} IS NOT DISTINCT FROM s.{quote(new)}), "
                        f"count(DISTINCT m.{quote(old)})" for old, new in pairs)
    with long(f"comparing {' and '.join(f'{old} with {new}' for old, new in pairs)} in every row of {t['name']} to "
              "prove a rename; raise max_seconds once, until a run has proven it"):
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
    renamed_to = {old: new for new, old in renamed.items()}
    # not one the source retires: that log column takes another name in this run
    followed = {n: into for n, type in log_columns if (into := had.get(n)) and into != type
                and family(into) == family(type) == family(types.get(renamed_to.get(n, n), into))
                and wider(type, into) == into}
    log_columns = [(n, followed.get(n, type)) for n, type in log_columns]
    pairs = [(table, name, into) for table, columns in ((t["mirror"], mirror), (t["log_table"], log_columns))
             for name, type in staged if (into := dict(columns).get(renamed.get(name, name), type)) != type
             and family(into) == family(type)]  # another family is a column that goes and comes, check() plans it
    # only a target that does not hold the staged type already needs the scan
    widened = [(table, name, wider(into, types[name]))
               for table, name, into in misfits(conn, [p for p in pairs if wider(p[2], types[p[1]]) != p[2]])]
    follow = [(t["log_table"], renamed_to.get(n, n), into) for n, into in followed.items()
              if (t["log_table"], renamed_to.get(n, n)) not in {w[:2] for w in widened}]
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
    if t["catalog"] not in (None, "data", "definition"):  # else a rule would take it for neither and act by halves
        raise Exception(f'connector "{t["type"]}" says catalog = {t["catalog"]!r}, which is neither "data" nor '
                        '"definition"; without the entry the source has a catalog of its own')
    version = getattr(connector, "driver_version", None)
    if version is not None and not (isinstance(version, str) and len(version) <= 200 and not CONTROL.search(version)):
        raise Exception(f'connector "{t["type"]}" says a driver_version that is no text of one line and at most 200 '
                        'characters, which every run records: give it a short one, such as "mylib 2.3.1", or none')
    sql(conn, "UPDATE _rowvioli.runs SET driver_version = $2 WHERE run = $1", [t["run"], version])
    try:
        connection = seal.unseal(os.environ["ROWVIOLI_KEY_FILE"], t["key_id"], t["source"], t["connection"])
    except Exception as e:
        raise Exception(f"the connection of source {t['source']} cannot be decrypted on worker {t['worker']}: {e}")
    # a directory is no secret, and a reason without it is not readable (decision 47)
    t["values"] = connection_values(connection, ("path",) if t["type"] == "file" else ())
    options = dict(t["options"])
    options.pop("renamed", None)  # the run's, not the connector's (decision 54)
    batches = stream(connector.read(connection, t["source_table"], options), t["type"])
    if batches is None:
        raise Exception("the connector delivered nothing, not even the columns")
    batches = whole(batches, t)

    def cut(name):  # Postgres keeps the first 63 bytes of a name, whole characters, and drops the rest (cases A20)
        return name.encode()[:63].decode(errors="ignore")
    if overlong := [n for n in batches.schema.names if cut(n) != n]:
        twins = [n for n in batches.schema.names if cut(n) == cut(overlong[0])]
        raise Exception(f"columns {' and '.join(twins)} of the source are equal in their first 63 bytes, the most "
                        "Postgres keeps of a name: give them names in the source that differ there" if twins[1:] else
                        f"column {overlong[0]} of the source is longer than 63 bytes, the most Postgres keeps of a name: "
                        "give it a shorter name in the source")
    t["own_types"] = {f.name for f in batches.schema if contract.OWN_TYPE.items() <= (f.metadata or {}).items()}
    if (gone := [k for k in t["key"] or [] if k not in batches.schema.names]):
        raise Exception(f"table {t['source_table']} has no column {', '.join(gone)}, which the key names: give the "
                        "table a key of the columns it has: " + ", ".join(batches.schema.names))
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
        except Exception as e:  # the driver gives what the connector raised in its stream as its own error, wrapped
            if raised:
                raise raised[0] from None
            t["step"] = "staging the rows"  # the target refused them, not the source
            # a value its column's type cannot hold (a timestamp before 4713 BC): Postgres names the column, no value
            at = re.fullmatch(r"COPY _stage, line \d+, column (.+)", dict(getattr(e, "details", None) or []).get(
                b"PG_DIAG_CONTEXT", b"").decode(errors="replace"))
            if (getattr(e, "sqlstate", None) or "").startswith("22") and at and \
                    at[1] in (types := dict(sql(conn, COLUMNS, ["pg_temp._stage"]))):
                raise Exception(f"{t['source_table']}: column {at[1]} has a value its type in the target, "
                                f"{types[at[1]]}, cannot hold (SQLSTATE {e.sqlstate}); cast it in a view of the source "
                                "or change it there") from None
            raise
    # zero rows protect a mirror that has rows; a first load or an empty mirror publishes them
    if rows_read == 0 and t["max_delete_share"] < 1 and sql(conn, "SELECT to_regclass($1)", [t["mirror"]])[0][0] and \
            sql(conn, f"SELECT 1 FROM ONLY {t['mirror']} LIMIT 1"):
        raise Exception("the source delivered zero rows; max_delete_share = 1.0 allows an empty table")
    # the driver writes Arrow's json only as json
    to_jsonb = [f"ALTER {quote(n)} TYPE {JSONB[type]} USING {quote(n)}::{JSONB[type]}"
                for n, type in sql(conn, COLUMNS, ["pg_temp._stage"]) if type in JSONB]
    if to_jsonb:
        sql(conn, "ALTER TABLE _stage " + ", ".join(to_jsonb))
    return rows_read


# json has no equality, so a comparison of it could not run: it is staged as jsonb, and the mirror's json of before is
# compared as jsonb while it goes
JSONB = {"json": "jsonb", "json[]": "jsonb[]"}


def whole(batches, t):
    """The values as the driver writes them whole, or the run fails naming the column. The driver writes a uint64 as
    bigint and wraps one above 2**63 - 1 to a negative number: as decimal128(20, 0) it is staged as numeric(20,0), and a
    mirror's bigint stays while it fits. It cuts a time finer than a microsecond, the finest Postgres holds."""
    # shortcut: top-level columns only, and not an interval's nanoseconds; upgrade when a source delivers one
    def held(type):
        if pa.types.is_uint64(type):
            return pa.decimal128(20, 0)
        if getattr(type, "unit", None) != "ns":
            return type
        return pa.timestamp("us", type.tz) if pa.types.is_timestamp(type) else \
            pa.time64("us") if pa.types.is_time64(type) else pa.duration("us")
    schema = pa.schema([f.with_type(held(f.type)) for f in batches.schema], metadata=batches.schema.metadata)
    if schema.equals(batches.schema):
        return batches

    def cast(column, field):
        try:
            return column.cast(field.type)  # a safe cast: a time it would cut raises
        except pa.ArrowInvalid:
            pin = "time" if pa.types.is_time(field.type) else \
                "timestamptz" if getattr(field.type, "tz", None) else "timestamp"  # a file brings no duration
            raise Exception(f"{t['source_table']}: column {field.name} has a time finer than a microsecond, which the "
                            "target does not hold; " + (f'columns = {{ {field.name} = "{pin}" }} reads it rounded to '
                                                        "microseconds" if t["type"] == "file" else
                                                        "cut it to microseconds in a view of the source")) from None
    return pa.RecordBatchReader.from_batches(schema, (pa.record_batch(
        [cast(c, f) for c, f in zip(b.columns, schema)], schema=schema) for b in batches))


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


def stream(batches, connector):
    """The driver's ingest needs the schema before the first batch; a connector may return any iterator. None for
    one without a batch. What is no record batch, or one of another schema than the first, fails naming the
    `connector`, instead of Arrow's words (ticket 17)."""
    if isinstance(batches, pa.RecordBatchReader):
        return batches
    batches = iter(batches)
    first = next(batches, None)
    if first is None:
        return None
    if not isinstance(first, pa.RecordBatch):
        raise odd(first, connector)

    def checked():
        for b in itertools.chain([first], batches):
            if not isinstance(b, pa.RecordBatch) or not b.schema.equals(first.schema):
                raise odd(b, connector)
            yield b
    return pa.RecordBatchReader.from_batches(first.schema, checked())


def odd(batch, connector):
    what = "a batch of another schema than its first" if isinstance(batch, pa.RecordBatch) else \
        f"a {type(batch).__name__}, not an Arrow record batch"
    return Exception(f'connector "{connector}" delivered {what}, which the contract does not allow')


def diff(conn, t, staged, mirror, plan):
    """Step 5, by the plan (decision 54): the rows that differ into the TEMP table _diff (docs/target.md "Comparing in
    the target"), over the columns of staging table and mirror together, every column list by name. Returns the
    counts."""
    had, staging = dict(mirror), dict(staged)
    # the mirror's column each reads: one that went under the change log's name for it, a retired one under its new
    # name and never compared with its successor, a renamed one under its old name
    read = {c: c for c in had if c not in plan["gone"]} | {plan["retired"].get(c, c): c for c in plan["gone"]} \
        | plan["renamed"]
    columns = staged + [(plan["retired"].get(c, c), JSONB.get(had[c], had[c])) for c in plan["gone"]]
    # a new column is null in the mirror once added, and one that went is null in the source, so a row differs only
    # if the other side has a value there
    s = ", ".join(f"s.{quote(c)}" if c in staging else f"NULL::{type}" for c, type in columns)
    m = ", ".join(f"m.{quote(read[c])}" + (f"::{type}" if had[read[c]] in JSONB else "") if c in read
                  else f"NULL::{type}" for c, type in columns)
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


def publish(conn, t, staged, delivered, mirror, log_columns, rows_read, counts, plan):
    """Step 6, one transaction in the order of decision 54: the plan, new columns, mirror, change log and its view,
    the columns table, loaded_at, attempts and the run's row. Raises, so nothing is published, when the table's row
    no longer gives it this target name."""
    names = ", ".join(quote(c) for c, _ in staged)
    logged = ", ".join(quote(c) for c in [*dict(staged), *(plan["retired"].get(c, c) for c in plan["gone"])])
    new = not mirror
    moved = plan["moved"]
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
    if t["long"]:  # the rows of the mirror and the change log, under the lock that load() named
        say(long=t["long"])
    if new:  # created inside publishing, so a mirror never exists empty
        key = f", PRIMARY KEY ({', '.join(quote(k) for k in t['key'])})" if t["key"] else ""
        sql(conn, f"CREATE TABLE {t['mirror']} (LIKE _stage{key})")
    else:
        add_columns(conn, t["mirror"], staged, [(moved.get(n, n), type) for n, type in mirror if n not in plan["gone"]])
    if t["key"] and plan["key"].get("by") != "definition":
        on = " AND ".join(f"d.{quote(k)} = m.{quote(k)}" for k in t["key"])
        kept = ""
        if plan["gone"]:  # a row that differs only in a column that went keeps its place in the mirror (story 5)
            ds, ms = (", ".join(f"{a}.{quote(c)}" for c, _ in staged) for a in "dm")
            kept = f" AND ROW({ds}) IS DISTINCT FROM ROW({ms})"
        sql(conn, f"DELETE FROM ONLY {t['mirror']} m USING _diff d WHERE d._op = 'D' AND {on}")
        # an update in place: as a delete and an insert, a consumer's foreign key onto the mirror refused it, or
        # cascaded the delete to its rows (ticket 17)
        values = ", ".join(f"{quote(c)} = d.{quote(c)}" for c, _ in staged)
        updated = rowcount(conn, f"UPDATE ONLY {t['mirror']} m SET {values} FROM _diff d WHERE d._op = 'U' AND {on}{kept}")
        sql(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _diff WHERE _op = 'I'")
        # the counts are the mirror's: a U only the change log gets, for a column that went, updates no row of it
        counts = {**counts, "updated": updated}
    else:  # without a key, or under another key (decision 54): replaced as a whole
        deleted = rowcount(conn, f"DELETE FROM ONLY {t['mirror']}")
        counts = {"inserted": rowcount(conn, f"INSERT INTO {t['mirror']} ({names}) SELECT {names} FROM _stage"),
                  "updated": 0, "deleted": deleted}
    if t["key"] and plan["key"]:  # once the old rows are gone, which may hold the new key twice
        sql(conn, f"ALTER TABLE {t['mirror']} ADD PRIMARY KEY ({', '.join(quote(k) for k in t['key'])})")
    if t["key"] and t["log"]:  # the change log's columns under the names the plan gave them
        write_log(conn, t, staged, [(moved.get(n, n), type) for n, type in log_columns], logged,
                  [moved.get(n, n) for n in plan.get("closed", [])])
    if t["long"]:
        say(long=None)
    record_columns(conn, t, delivered, mirror, log_columns, changes)
    # the table lock guards the table, not its name, which an apply may have given to another table meanwhile
    # (decision 53). Last, so the row lock that holds off an apply until COMMIT is taken after every wait on a mirror
    if not (claimed := sql(conn, """UPDATE _rowvioli.tables SET loaded_at = now(), attempts = 0
                                     WHERE id = $1 AND enabled AND target_schema = $2 AND target_table = $3
                                 RETURNING (options -> 'renamed')::text""", [t["id"], t["schema"], t["table"]])):
        [(name, enabled)] = sql(conn, "SELECT target_schema || '.' || target_table, enabled FROM _rowvioli.tables"
                                      " WHERE id = $1", [t["id"]])
        raise Exception(f"the target name changed to {name} while this run loaded {t['name']}; nothing was published, "
                        f"the next run loads {name}" if enabled else
                        f"the table left the definition while this run loaded {t['name']}; nothing was published")
    # decision 54: a rename stated since the claim that would act could act no more after this run, which adds the new
    # column (and lets the old one go, or fills it empty for a file)
    if lost := [f"{old} to {new}" for new, old in acting(json.loads(claimed[0][0] or "null"), dict(mirror),
                                                          dict(delivered), dict(log_columns)).items()
                if plan["renamed"].get(new) != old]:
        raise Exception(f"the definition renames column {' and '.join(lost)} since this run claimed {t['name']}; "
                        "nothing was published, the next run renames it")
    sql(conn, """UPDATE _rowvioli.runs SET status = 'ok', finished_at = clock_timestamp(), rows_read = $2,
                        inserted = $3, updated = $4, deleted = $5 WHERE run = $1""",
        [t["run"], rows_read, counts["inserted"], counts["updated"], counts["deleted"]])
    sql(conn, "COMMIT")
    return {"status": "ok", **counts}


def lock(conn, t):
    """Decision 54: opens the publishing transaction holding mirror, change log and history view, taken in one
    statement that does not wait and tried again for up to ten seconds. A run that waited for one while holding
    another could deadlock with a consumer who reads them in another order (story 43). Every later wait for a lock in
    the transaction ends after 50 ms, far below the second after which Postgres looks for a deadlock: the run never
    waits while it holds what blocks the readers of the mirror (a consumer's table with a foreign key to it, the
    table's row while an apply holds it)."""
    objects = ", ".join(n for n in (t["mirror"], t["log_table"], t["history"])
                        if sql(conn, "SELECT to_regclass($1) IS NOT NULL", [n])[0][0])
    # the history view is created again, which only a member of its owner may, and given back to its owner, which
    # needs CREATE on the schema; a lock of a view takes its owner's rights on the change log (story 43, ticket 15)
    for owner, me, schema in sql(conn, """
            SELECT relowner::regrole::text, quote_ident(current_user), relnamespace::regnamespace::text FROM pg_class
             WHERE oid = to_regclass($1) AND relowner <> current_user::text::regrole
               AND NOT (pg_has_role(relowner, 'MEMBER') AND has_schema_privilege(relowner, relnamespace, 'CREATE')
                        AND has_table_privilege(relowner, $2, 'UPDATE, DELETE, TRUNCATE'))""", [t["history"], t["log_table"]]):
        raise Exception(f"the history view {t['history']} is owned by {owner}, which the run cannot keep as its owner "
                        f"when it creates the view again for a change of columns: the worker's role must be a member of "
                        f"{owner}, and {owner} needs CREATE on schema {schema} and UPDATE on the change log "
                        f"{t['log_table']}; or give it back, ALTER VIEW {t['history']} OWNER TO {me}")
    while True:
        sql(conn, "BEGIN")
        try:
            sql(conn, f"LOCK TABLE {objects} IN ACCESS EXCLUSIVE MODE NOWAIT")
            sql(conn, "SET LOCAL lock_timeout = '50ms'")
            t["locked"] = True
            return
        except Exception as e:
            sql(conn, "ROLLBACK")
            if getattr(e, "sqlstate", None) != "55P03":  # lock_not_available
                raise
            if time.monotonic() > t["tries"]:  # since the first try (load)
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


# what a person put on a view besides grants and its options (OPTIONS), as the statements that put it there again, in
# this order: its comment, its triggers and rules with their comments, its owner; its columns' comments and defaults are
# (column, comment, default)
KEPT = """
    SELECT s FROM (
        SELECT 1, format('COMMENT ON VIEW %s IS %L', $1, obj_description(to_regclass($1), 'pg_class'))
         WHERE obj_description(to_regclass($1), 'pg_class') IS NOT NULL
        UNION ALL SELECT 2, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid = to_regclass($1) AND NOT tgisinternal
        UNION ALL SELECT 2, pg_get_ruledef(oid) FROM pg_rewrite WHERE ev_class = to_regclass($1) AND rulename <> '_RETURN'
        UNION ALL SELECT 3, format('COMMENT ON TRIGGER %I ON %s IS %L', tgname, $1, obj_description(oid, 'pg_trigger'))
          FROM pg_trigger WHERE tgrelid = to_regclass($1) AND obj_description(oid, 'pg_trigger') IS NOT NULL
        UNION ALL SELECT 3, format('COMMENT ON RULE %I ON %s IS %L', rulename, $1, obj_description(oid, 'pg_rewrite'))
          FROM pg_rewrite WHERE ev_class = to_regclass($1) AND obj_description(oid, 'pg_rewrite') IS NOT NULL
        UNION ALL SELECT 4, format('ALTER VIEW %s OWNER TO %s', $1, relowner::regrole) FROM pg_class
         WHERE oid = to_regclass($1) AND relowner <> current_user::text::regrole) k(n, s) ORDER BY n"""
ON_COLUMNS = """SELECT attname, col_description(attrelid, attnum), pg_get_expr(d.adbin, d.adrelid)
                  FROM pg_attribute a LEFT JOIN pg_attrdef d ON (d.adrelid, d.adnum) = (a.attrelid, a.attnum)
                 WHERE attrelid = to_regclass($1) AND attnum > 0
                   AND (col_description(attrelid, attnum) IS NOT NULL OR d.oid IS NOT NULL)"""
OPTIONS = "SELECT array_to_string(reloptions, ', ') FROM pg_class WHERE oid = to_regclass($1)"
# a rule or trigger on the view $1 that names a column this run renames, retires ($3, $4: JSON lists) or drops from the
# mirror ($2, whose dropped ones are in $4 too), of the view, of the change log $5 or of the mirror: created again from its
# text, it would name another column or none
BOUND = """
    SELECT DISTINCT format('%s %s', CASE WHEN r.oid IS NULL THEN 'trigger' ELSE 'rule' END, coalesce(r.rulename, g.tgname)),
           format('column %s of %s.%s', a.attname, n.nspname, c.relname)
      FROM pg_depend d JOIN pg_attribute a ON (a.attrelid, a.attnum) = (d.refobjid, d.refobjsubid)
      JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
      LEFT JOIN pg_rewrite r ON d.classid = 'pg_rewrite'::regclass AND r.oid = d.objid
      LEFT JOIN pg_trigger g ON d.classid = 'pg_trigger'::regclass AND g.oid = d.objid
     WHERE d.refclassid = 'pg_class'::regclass AND d.deptype = 'n' AND coalesce(r.ev_class, g.tgrelid) = to_regclass($1)
       AND r.rulename IS DISTINCT FROM '_RETURN' AND c.oid IN (to_regclass($1), to_regclass($2), to_regclass($5))
       AND a.attname IN (SELECT json_array_elements_text(CASE WHEN c.oid = to_regclass($2) THEN $4 ELSE $3 END::json))
     ORDER BY 1, 2"""


# the publications of a table's updates or deletes that need its primary key as its replica identity
PUBLISHED = """
    SELECT string_agg(format('publication %I', p.pubname), ' and ' ORDER BY p.pubname)
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_publication_tables pt ON (pt.schemaname, pt.tablename) = (n.nspname, c.relname)
      JOIN pg_publication p ON p.pubname = pt.pubname
     WHERE c.oid = $1::regclass AND c.relreplident = 'd' AND (p.pubupdate OR p.pubdelete)"""


def carry_out(conn, t, plan):
    """Decision 54, under the lock: the history view goes, since Postgres alters no column a view reads (write_log
    creates it again with its options, gives its grants again, a renamed column's under its new name, and puts back
    what a person put on it), then the plan. Returns what the columns table says beyond the catalogue (decision
    54)."""
    renamed_to = {old: new for new, old in plan["renamed"].items()}
    t["grants"] = [(p, renamed_to.get(c, c), *rest) for p, c, *rest in sql(conn, GRANTS, [t["history"]])]
    on_columns = [(quote(plan["moved"].get(c, c)), text, default)
                  for c, text, default in sql(conn, ON_COLUMNS, [t["history"]])]
    t["kept"] = [f"COMMENT ON COLUMN {t['history']}.{c} IS {literal(text)}" for c, text, _ in on_columns if text] + [
        f"ALTER VIEW {t['history']} ALTER COLUMN {c} SET DEFAULT {default}" for c, _, default in on_columns if default] \
        + [s for (s,) in sql(conn, KEPT, [t["history"]])]  # the owner last
    t["view_options"] = sql(conn, OPTIONS, [t["history"]])
    for what, column in sql(conn, BOUND, [t["history"], t["mirror"], json.dumps(list(plan["moved"])),
                                          json.dumps([*plan["moved"], *plan["gone"]]), t["log_table"]]):
        t.setdefault("blocked", []).append(
            f"the history view {t['name']}__history is created again for a change of columns, but {what} on it names "
            f"{column}, which this run renames or drops, so it cannot be carried over")
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
    moved = plan["moved"]
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
            why = f"the key of {t['name']} would change from ({', '.join(was)}) to ({', '.join(key)})"
            dropped = alter(conn, t, why, f"ALTER TABLE {t['mirror']} DROP CONSTRAINT {quote(name)}", t["mirror"],
                            constraint=name)
            # without its primary key Postgres refuses the deletes of a mirror whose deletes a publication publishes
            if published := sql(conn, PUBLISHED, [t["mirror"]])[0][0]:
                t.setdefault("blocked", []).append(
                    f"{why}, but {published} publishes its updates and deletes, for which the primary key is its "
                    f"replica identity: give it another for the change, ALTER TABLE {t['mirror']} REPLICA IDENTITY FULL")
        # Postgres leaves NOT NULL behind, also where LIKE copied it; a column still in a key it refuses to free
        if (loose := [c for c in was if c not in key]) and dropped:
            for table, named in [(t["mirror"], {}), (t["log_table"], plan["retired"])][:2 if plan["key"]["log"] else 1]:
                # one retired in this run has its new name in the change log already
                sql(conn, f"ALTER TABLE {table} " + ", ".join(f"ALTER {quote(named.get(c, c))} DROP NOT NULL"
                                                              for c in loose))
        if by == "definition" and plan["key"]["log"]:  # a stretch of the change log begins under the new key
            [(now,)] = sql(conn, "SELECT to_json(now()) #>> '{}'")  # ISO 8601, whatever the DateStyle
            # without a comment (0.4.1) the one key before, a column retired in this run under its new name
            keys = stretches(conn, t) or [{"key": [plan["retired"].get(c, c) for c in was]}]
            keys += [{"from": now, "key": key}]
            note = KEYS_NOTE + keys_of_log(conn, t, keys)
        changes.update({c: {**changes.get(c, {}), "by": by, "note": note} for c in {*was, *key}})  # a rename keeps was
    for name in plan["gone"]:
        [(note,)] = sql(conn, DROPS_WITH, [t["mirror"], name])
        changes[name] = {"note": f"{note} went with it" if note else None}
        if name in plan["retired"]:  # it comes back anew: a rename before was of the column the change log keeps
            changes[name]["was"] = None
        alter(conn, t, f"column {name} " + ("has another type in the source" if name in plan["retired"]
                                         else "is gone from the source") + f" and would leave the mirror {t['name']}",
              f"ALTER TABLE {t['mirror']} DROP COLUMN {quote(name)}", t["mirror"], [name])
    for name in plan["unpinned"]:  # decision 54: a type the definition gave, and took back
        changes[name]["by"] = changes[plan["retired"][name]]["by"] = "definition"
    for table in (t["mirror"], t["log_table"]):  # decision 54, one ALTER per table, so it is rewritten at most once
        if widened := [(name, type) for into, name, type in plan["widen"] if into == table]:
            columns = ", ".join(f"column {name} to {type}" for name, type in widened)
            hand = set(plan["followed"]) if table == t["log_table"] else set()
            why = " and ".join(w for w, some in [("for values of the source", len(widened) > len(hand)),
                                                 ("to follow the mirror, which a person widened", hand)] if some)
            with long(f"widening {table}, {columns}; raise max_seconds once, until a run has widened it"):
                alter(conn, t, f"{table} would be widened {why}, {columns}",
                      f"ALTER TABLE {table} " + ", ".join(f"ALTER {quote(n)} TYPE {type}" for n, type in widened),
                      table, [n for n, _ in widened], drop=False)
    if t.get("blocked"):
        raise Exception("; and ".join(t["blocked"]) + ": change or drop that, and the next run goes on")
    return changes


# the note in the columns table of a change of key, before the comment's text (the reader's versions may come first)
KEYS_NOTE = "the change log's keys: "
RETIRED_NOTE = "the change log's comment: "  # the note of a retired column, before its comment's text


def comments(conn, t):
    """Decision 54: what the change log says of itself, the comment on each of its columns by name (None for none):
    on _op its keys, on a retired column whose old values it keeps. Empty without a change log."""
    return dict(sql(conn, "SELECT attname, col_description(attrelid, attnum) FROM pg_attribute WHERE attrelid = "
                          "to_regclass($1) AND attnum > 0 AND NOT attisdropped", [t["log_table"]]))


def retired_comment(note):
    """The text of a retired column's comment, from its note in the columns table, which may go on after it."""
    return json.dumps(json.JSONDecoder().raw_decode(note.partition(RETIRED_NOTE)[2])[0])


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
    catalogue names it then. Every object is named with its schema, also one on the search path: the catalogue names
    them under an empty search path, while the change runs under the run's own, which a consumer's code it calls (a
    check constraint's function, an event trigger) may need."""
    sql(conn, "SAVEPOINT alter")  # under the lock_timeout of lock()
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
        sql(conn, "SET LOCAL search_path = ''")  # pg_describe_object then names every object with its schema
        found = sql(conn, IN_THE_WAY, [table, json.dumps(columns), t["history"], constraint, drop])
        sql(conn, "ROLLBACK TO SAVEPOINT alter")  # the search path as it was
        named = "; ".join(f"{d} depends on {w}" for d, w, history in found if not history)
        if state == "55P03":
            t.setdefault("blocked", []).append(f"{why}, but {named}, in use, so the run did not wait for it" if named
                                               else f"{why}, but an object that depends on it was in use, so "
                                                    "Postgres did not name it; the next run does")
        elif named or not found:  # else only the history view, whose drop is stopped already with what is in its way
            detail = named or details["PG_DIAG_MESSAGE_DETAIL"].replace("\n", "; ")
            t.setdefault("blocked", []).append(f"{why}, but {detail}")
    return done


def write_log(conn, t, staged, log_columns, names, closed=None):
    """After the mirror is published, in the same transaction: a log that exists gets the diff, a new one begins
    with the whole mirror, so that replaying a log from the last change of key always gives the mirror; `closed`, the
    columns a person dropped from the mirror, get a U for every row whose latest version differs in one. The
    history view is created when missing and replaced when the log got a column; otherwise it is not touched, so takes
    no lock."""
    if log_columns:
        widened = add_columns(conn, t["log_table"], staged, log_columns)
        rows = f"SELECT _op, {names} FROM _diff"
    else:
        sql(conn, f"CREATE TABLE {t['log_table']} (_run bigint, _op text, _loaded_at timestamptz, LIKE {t['mirror']})")
        # its one key said, so that a change of key the columns table noted for an earlier change log does not stop it
        keys_of_log(conn, t, [{"key": t["key"]}])
        rows = f"SELECT 'I', {names} FROM ONLY {t['mirror']}"
    # now() is the transaction's moment, the one that goes into tables.loaded_at
    sql(conn, f"INSERT INTO {t['log_table']} (_run, _loaded_at, _op, {names}) SELECT $1, now(), * FROM ({rows}) r",
        [t["run"]])
    if closed:  # after this run's rows, in one pass over the change log (tickets 17, M3, and 18)
        key, mine, mirrored, gone = (", ".join(f"{a}{quote(c)}" for c in cs) for a, cs in (
            ("", t["key"]), ("", dict(staged)), ("m.", dict(staged)), ("", closed)))
        # a version is still current where it differs from the mirror, which has a value where the source kept one
        current = " OR ".join(f"l.{quote(c)} IS DISTINCT FROM m.{quote(c)}" if c in dict(staged) else
                              f"l.{quote(c)} IS NOT NULL" for c in closed)
        sql(conn, f"""INSERT INTO {t['log_table']} (_run, _loaded_at, _op, {mine})
                       SELECT $1, now(), 'U', {mirrored} FROM ONLY {t['mirror']} m
                         JOIN (SELECT DISTINCT ON ({key}) {key}, {gone} FROM ONLY {t['log_table']}
                                ORDER BY {key}, _loaded_at DESC, _op = 'D') l USING ({key})
                        WHERE {current}""", [t["run"]])
    if log_columns and not widened and sql(conn, "SELECT to_regclass($1) IS NOT NULL", [t["history"]])[0][0]:
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
    # decision 54: the options a person gave it, which a view created or replaced without them loses
    [(options,)] = t.pop("view_options", None) or sql(conn, OPTIONS, [t["history"]]) or [(None,)]
    sql(conn, f"CREATE OR REPLACE VIEW {t['history']}{f' WITH ({options})' if options else ''} AS"
              + "\n        UNION ALL".join(branches))
    for privilege, column, grantee, option, grantor in t.pop("grants", []):  # those carry_out found before the drop
        # decision 54: a grant a grantee passed on comes back from it, given as that role; Postgres 14 to 17 take no
        # other grantor than the current role (GRANTED BY). Where the run's role may not act as it, the grantor may
        # no longer reach the view (USAGE on its schema) or no longer holds the grant option (a column's grant outlives
        # the table's option it was given under, and given again it would be none, with a warning), the grant is the
        # run's role's own
        grant = (f"GRANT {privilege}{f' ({quote(column)})' if column else ''} ON {t['history']} TO {grantee}"
                 + (" WITH GRANT OPTION" if option else ""))
        held = (f"has_column_privilege($1::regrole, $2, {literal(column)}, $3)" if column else
                "has_table_privilege($1::regrole, $2, $3)")
        if grantor and sql(conn, f"SELECT {held}", [grantor, t["history"], f"{privilege} WITH GRANT OPTION"])[0][0]:
            sql(conn, "SAVEPOINT grantor")
            try:
                sql(conn, f"SET LOCAL ROLE {grantor}")
                sql(conn, grant)
                sql(conn, "RESET ROLE")
                continue
            except Exception as e:
                if getattr(e, "sqlstate", None) != "42501":  # insufficient_privilege
                    raise
                sql(conn, "ROLLBACK TO SAVEPOINT grantor")  # the role too
        sql(conn, grant)
    for statement in t.pop("kept", []):  # those carry_out found before the drop
        sql(conn, statement)


def record_columns(conn, t, delivered, mirror, log_columns, changes):
    """Decision 54, last in publishing, in its transaction: what the columns of mirror and change log are now
    against what `_rowvioli.columns` says, as rows of `columns__log` with this transaction's moment. `mirror` and
    `log_columns` are the columns as the run found them, so that what differs from the record without this run is by
    hand.
    `changes` gives fields of the plan by column name (`was`, `note`, `by`). Notifies on `rowvioli_schema` when
    anything but a first fill was recorded."""
    def state(mirror, log_columns):
        return {**{n: (type, False) for n, type in log_columns if n not in ("_run", "_op", "_loaded_at")},
                **{n: (type, True) for n, type in mirror}}
    found = state(mirror, log_columns)
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
    # the text to put back a retired column's comment (check) goes on with every later row of it, as `was` does, also
    # under a new target name
    retired = {r[2]: RETIRED_NOTE + retired_comment(r[9])
               for r in recorded if r[9] and RETIRED_NOTE in r[9] and not r[6]}
    # a mirror renamed by hand: what was recorded under a name that is no table any more is closed
    rows = [{**dict(zip(names, r)), "op": "D", "by": "hand"} for r in recorded if r[10]]
    rows += [{**r, "op": "D", "by": "hand"} for name, r in old.items() if name not in now]
    for name, (type, in_mirror) in now.items():
        # one the source did not deliver keeps the type it last did, a retired one that of the name it had (story 34)
        last = old.get(changes.get(name, {}).get("was", name), {}).get("source_type", type)
        row = dict(target_schema=t["schema"], target_table=t["table"], column=name, type=type,
                   source_type=delivered.get(name, last), key=key.get(name), mirror=in_mirror, was=None,
                   note=None if in_mirror else retired.get(name))
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
    # whether another reader than the last successful run's gave these columns, perhaps, and not the source
    [(differs, note)] = sql(conn, """
        SELECT (l.program_version, l.driver_version) IS DISTINCT FROM (c.program_version, c.driver_version),
               format('program %s to %s, driver %s to %s', coalesce(l.program_version, 'none'),
                      coalesce(c.program_version, 'none'), coalesce(l.driver_version, 'none'),
                      coalesce(c.driver_version, 'none'))
          FROM _rowvioli.runs c LEFT JOIN LATERAL (SELECT program_version, driver_version FROM _rowvioli.runs
                WHERE "table" = c."table" AND status = 'ok' AND run < c.run ORDER BY run DESC LIMIT 1) l ON true
         WHERE c.run = $1""", [t["run"]])
    pinned = t["pinned"]  # a type the definition gives (decision 54)
    for r in rows:  # the cause: what the plan says, else the definition where it gives the column, else the reader
        if (r["target_schema"], r["target_table"]) == (t["schema"], t["table"]):
            r.update(changes.get(r["column"], {}))
            # REST's columns are all the definition's, also one taken out of it; a retired one is by its name's cause
            if r["by"] == "source" and (t["catalog"] == "definition" or r["column"] in pinned or r["was"] in pinned):
                r["by"] = "definition"
        if r["by"] == "source" and differs:
            r.update({"by": "reader", "note": "; ".join(filter(None, [note, r["note"]]))})
    recordset = """jsonb_to_recordset($1::jsonb) AS x(op text, target_schema text, target_table text, "column" text,
                type text, source_type text, "key" int, mirror boolean, was text, "by" text, note text)"""
    payload = json.dumps(rows)
    fields = 'target_schema, target_table, "column", type, source_type, "key", mirror, was, "by", note'
    sql(conn, f"INSERT INTO _rowvioli.columns__log SELECT $2::bigint, op, now(), {fields}, $3::int FROM {recordset}",
        [payload, t["run"], t["id"]])
    sql(conn, f"""DELETE FROM _rowvioli.columns c USING {recordset} WHERE x.op = 'D'
                     AND (c.target_schema, c.target_table, c."column") = (x.target_schema, x.target_table, x."column")""",
        [payload])
    sql(conn, f"""INSERT INTO _rowvioli.columns SELECT {fields}, $2::int FROM {recordset} WHERE op <> 'D'
                  ON CONFLICT (target_schema, target_table, "column") DO UPDATE SET type = excluded.type,
                  source_type = excluded.source_type, "key" = excluded."key", mirror = excluded.mirror,
                  was = excluded.was, "by" = excluded."by", note = excluded.note, id = excluded.id""",
        [payload, t["id"]])
    if any(r["by"] != "found" for r in rows):
        sql(conn, "SELECT pg_notify('rowvioli_schema', json_build_object('schema', $1::text, 'table', $2::text,"
                  " 'run', $3::bigint)::text)", [t["schema"], t["table"], t["run"]])


def add_columns(conn, table, staged, existing):
    """Decision 17: adds the source's columns the table lacks, under the lock publish took first (story 43). Says
    whether it added one. Not plan["widen"], which widens types."""
    have = dict(existing)
    new = [(name, type) for name, type in staged if name not in have]
    for name, type in new:
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
                     r"(?:Failed to (?:prepare query|execute query(?: '.*?')?|execute prepared statement|execute COPY statement): )?"
                     r"(?:PGRES_[A-Z_]+ )?(?:ERROR:\s+)?", re.S)


# a value quoted in a message without a SQLSTATE, a connector's of one's own say: last, after a colon (`invalid input
# syntax for type integer: "abc"`), or before `is out of range` (`value "…"`, bare for a float), as Postgres quotes them
VALUE = re.compile(r'(?<=: )"[^\n]*"$|(?:^|(?<=\s))"[^\n]*"(?= is out of range)')
# the SQLSTATE in arrow-odbc's text of a driver's diagnostic record, the ODBC standard's for every driver
# (`ODBC emitted an error calling 'SQLExecDirect': State: 22P02, Native error: 1, Message: ...`); a driver that sets
# none leaves five NULs there. Before it the ODBC call that failed: a failure to connect (SQLDriverConnect) comes before
# any row and is shown, whatever its SQLSTATE (the driver manager's `Can't open lib` is a 01000)
ODBC_STATE = re.compile(r"(?:\bcalling '(\w+)':\s*)?\bState: ([^,]{5}), Native error: -?\d+, Message: ")
OWN = os.path.dirname(os.path.abspath(__file__)) + os.sep  # the program's code, its shipped connectors among it


def reason_line(values, e, step, source=None, name=None):
    """The reason as it is stored, shown and logged: the first line of the driver's message without its wrapper,
    joined with the next when it ends in a colon, without a value of a row (VALUE), scrubbed last, so that a password
    that occurs in the wrapper (`x`, `query`) does not keep the wrapper from being cut. A message that holds a
    traceback gives the text before it, or the exception's own line (the traceback's last) when nothing is before it;
    ADBC cuts long messages, so the end may be missing. A line saying so, with the exception's type, when there is no
    message. A database's message that may hold a row's value is withheld (withheld); `source` is the source table,
    `name` the source's."""
    if reason := withheld(e, step, source, name):
        return scrub(values, CONTROL.sub("?", reason))
    # first only a value with a line break or another control character, which the cut and the ? would break up
    text = scrub([v for v in values if v and CONTROL.search(v)], str(e)).strip()
    raised = e.__traceback__
    while raised and raised.tb_next:
        raised = raised.tb_next
    # the program's own reason is one line: a name in it may hold a control character. A plain Exception raised
    # elsewhere, by a connector of one's own, is cut as a driver's message is, since its next lines may quote a row
    if type(e) is Exception and raised and os.path.abspath(raised.tb_frame.f_code.co_filename).startswith(OWN):
        # a name its way out quotes with one is written with Unicode escapes, so that the statement works when pasted
        text = re.sub(r'"(?:[^"]|"")*"', lambda m: "U&" + CONTROL.sub(
            lambda c: f"\\{ord(c[0]):04X}", m[0].replace("\\", "\\\\")) if CONTROL.search(m[0]) else m[0], text)
        text = CONTROL.sub("?", text)
    before, _, traceback = text.partition("Traceback (most recent call last)")
    before = re.sub(r"\s*Detail: Python exception:\s*$", "", before)
    first, *rest = (WRAPPER.sub("", before).strip() or traceback.strip().split("\n")[-1]).split("\n")
    line = f"{first} {rest[0].strip()}" if first.endswith(":") and rest else first
    line = VALUE.sub('"***"', line).strip()
    where = "source" if step == "reading the source" else "target"
    line = re.sub(r"canceling statement due to statement timeout$", rf"\g<0>: the statement_timeout of the role in the "
                  rf"{where} ended it; to let a run take longer, ALTER ROLE <its role> IN DATABASE <its database> SET "
                  "statement_timeout = 0", line)
    # a failed connection to a source, through ADBC or ODBC: a variable changed since apply is not in it (ticket 17)
    if step == "reading the source" and (re.search(r"\bFailed to connect\b|\bcalling 'SQLDriverConnect'", str(e))
                                         or str(getattr(e, "sqlstate", None) or "").startswith("28")):
        line += ("; the connection is the one the last apply stored: after changing a variable it reads, run apply "
                 "again")
    if step == "publishing":  # a row of the mirror is updated in place, deleted only where the source deleted it
        line = re.sub(r'^update or delete on table "[^"]*" violates foreign key constraint "[^"]*" on table ("[^"]*")$',
                      r"\g<0>: the source deleted a row that table \1 refers to, or changed the value it refers to; "
                      "delete the rows there that refer to it, or give the constraint ON DELETE CASCADE or ON DELETE "
                      "SET NULL (ON UPDATE CASCADE for a changed value)", line)
        # and the update checks a unique index per row, where values swapped between rows passed a delete and insert
        line = re.sub(r'^duplicate key value violates unique constraint "[^"]*"$', r"\g<0>: Postgres checks a unique "
                      "index on the mirror row by row, so it refuses a value that moves from one row to another within "
                      "a run, as well as one the source holds twice; drop it, or put in its place a constraint that "
                      "Postgres checks at the end of the statement: ALTER TABLE <the mirror> ADD UNIQUE (<its "
                      "columns>) DEFERRABLE", line)
    if step != "reading the source":  # a source may have a table of that name
        line = re.sub(r"must be owner of table \S+$", r"\g<0>: the worker's role must own it, or be a member of the "
                      r"role that owns it, to change its columns with the mirror's (ALTER TABLE <it> OWNER TO <the "
                      r"worker's role>)", line)
        # a target schema: without USAGE even the look for the mirror is refused (_rowvioli's rights are init's)
        line = re.sub(r"permission denied for schema (?!_rowvioli$)(\S+)$", r"\g<0>: the worker's role needs USAGE "
                      r"and CREATE on it (GRANT USAGE, CREATE ON SCHEMA \1 TO <the worker's role>)", line)
        line = re.sub(r"permission denied for table (columns(?:__log)?)$", r"\g<0>: the worker's role lacks a right on "
                      r"_rowvioli.\1, which rowvioli init printed with the upgrade to version 4 "
                      '(docs/operation.md "The target")', line)
    return scrub(values, line) or f"the driver gave no message while {step} ({type(e).__name__})"


# a frame of a function in the context Postgres gives an error, in every language that names its frames:
# `PL/pgSQL function guard() line 3 at RAISE`, `SQL function "f" statement 1`, `PL/Python function "guard"`
FRAME = re.compile(r'(?:PL/\w+|SQL) (?:function|procedure) ("(?:[^"]|"")*"|(?:"[^"]*"|[^\s(])+\(.*?\))')
# Postgres's own messages of a violated constraint, which show names and no value (of class 23, not under a function)
CONSTRAINT = re.compile(r'duplicate key value violates unique constraint "[^"]*"'
                        r'|(?:insert or update|update or delete) on table "[^"]*" violates foreign key constraint '
                        r'"[^"]*"(?: on table "[^"]*")?'
                        r'|null value in column "[^"]*" of relation "[^"]*" violates not-null constraint'
                        r'|new row for relation "[^"]*" violates check constraint "[^"]*"'
                        r'|conflicting key value violates exclusion constraint "[^"]*"'
                        # and those of a change of a table that re-checks its rows (a widening, a new primary key)
                        r'|check constraint "[^"]*" of relation "[^"]*" is violated by some row'
                        r'|column "[^"]*" of relation "[^"]*" contains null values'
                        r'|could not create (?:unique index|exclusion constraint) "[^"]*"')


# the SQLSTATEs whose messages name objects, users or limits and never a value of a row, and which an operator needs.
# Codes, not classes: in a class, some code's message quotes what a cast or a function was given (`relation "Anna" does
# not exist` 42P01, `syntax error in tsquery: "…"` 42601, `could not open file "…"` 58P01, `cross-database references
# are not implemented: …` 0A000). A code comes in only with the reason why its message holds no value. A constraint's
# message (class 23) is known by its words (CONSTRAINT); an ODBC driver's failure to connect is the connector's own
SHOWN = {"08000", "08001", "08003", "08004", "08006", "08P01", "08S01",  # a connection lost or refused: a host
         "28000", "28P01",  # a refused login: the user
         "25006",  # a read-only transaction, as on a standby: the statement's kind
         "2BP01",  # objects that depend on one to be dropped: the objects
         "40001", "40P01",  # a serialization failure, a deadlock: fixed words
         "42501",  # a missing right: an object that exists
         "53000", "53100", "53200", "53300", "53400",  # resources, a full disk: a file, a size, a role
         "55006", "55P03",  # an object in use: the object
         "57014", "57P01", "57P02", "57P03", "57P04", "57P05"}  # a cancel, a timeout, a shutdown: fixed words


# an object a statement names that does not exist: a table, a column, a type or a function; ODBC's for a table and a
# column. Its message may name a row's value (`relation "Anna" does not exist` of ::regclass), so the program says it
MISSING = {"42P01", "42703", "42704", "42883", "42S02", "42S22"}


def withheld(e, step, source, name=None):
    """Decision 54, item 8, the one rule for a database's message, of the source or the target, through ADBC or ODBC:
    it reaches a reason only where the SQLSTATE the driver gives says that it holds names alone (SHOWN),
    or as Postgres's own message of a violated constraint, and never from under a consumer's function. Every other is
    withheld: a value's (class 22), a consumer's RAISE or ASSERT (P0001, P0004) or a function in C (it names no frame),
    a code the program does not know, a driver's HY000 or none. Returns the reason, which names what the program
    knows: the function its frame names in the context the driver gives, in whatever language (`PL/pgSQL function
    guard() line 3 at RAISE`, `SQL function "f" statement 1`, `PL/Python function "guard"`), the SQLSTATE, the source
    table or the target. None for a message to show, and for one without a SQLSTATE: the program's own, a connector's,
    libpq's before a server answered, which reason_line shows without a quoted value."""
    details = {k.decode(): v.decode(errors="replace") for k, v in getattr(e, "details", None) or []}
    text = str(e)
    odbc = ODBC_STATE.search(text)
    if not details and odbc and odbc[1] == "SQLDriverConnect":
        return None
    state = details.get("PG_DIAG_SQLSTATE") or (odbc and odbc[2])
    function = FRAME.search(details.get("PG_DIAG_CONTEXT") or text.partition("\nCONTEXT:  ")[2])
    message = details.get("PG_DIAG_MESSAGE_PRIMARY") or WRAPPER.sub("", text).split("\n")[0]
    # a constraint's words count only as Postgres's own: of class 23 and not under a consumer's code, which may copy them
    if not function and str(state).startswith("23") and CONSTRAINT.fullmatch(message) \
            or not (function or state and state not in SHOWN):
        return None
    who = f"function {function[1]}" if function else "a function" if state in ("P0001", "P0004") else "a statement"
    where = "source" if step == "reading the source" else "target"
    if state in MISSING and where == "source" and not function:  # the program's own words, which hold no value
        return (f"an object the statement reading {source} names does not exist (SQLSTATE {state}): the table itself, "
                f"a column, or one a view of it reads; rowvioli list {name} shows the tables, and a table renamed or "
                "moved in the source keeps its mirror and history when the definition names it anew and keeps its "
                "target_table")
    return (f"{who} raised an error{f' (SQLSTATE {state})' if state and state.isalnum() else ''} in the {where}"
            f"{f', reading {source}' if source and where == 'source' else ''}; its message may hold a row's values, "
            f"so it is left out here: the {where}'s server log{' or a trace' if where == 'source' else ''} has it")


def scrub(values, text):
    """`text` with each of `values` replaced by `***`: as written, stripped, and as repr writes it in quotes."""
    values = [w for v in values if v for w in (v, v.strip(), repr(v)[1:-1], repr(v.strip())[1:-1])]
    for value in sorted(filter(None, values), key=len, reverse=True):  # a whole URL before its parts
        text = text.replace(value, "***")
    return text


def lost(e):
    """Whether Postgres ended the connection (a restart, pg_terminate_backend), which a reason says in our words. The
    driver gives no SQLSTATE where the server ended it between two statements, only libpq's words."""
    return getattr(e, "sqlstate", None) in ("57P01", "57P02") or not getattr(e, "sqlstate", None) and bool(re.search(
        r"terminating connection due to administrator command|server closed the connection unexpectedly"
        r"|no connection to the server", str(e)))


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


@contextlib.contextmanager
def long(what):
    """Decision 54: a step of a change that may outlast max_seconds, said to the worker, which names it if it ends the
    run meanwhile, and its end; nothing for None."""
    if what:
        say(long=what)
    try:
        yield
    finally:
        if what:
            say(long=None)


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
    try:
        conn = target.connect(pooler=False)  # the worker that started this process checked for a pooler
        t = claim(conn, worker, source, table)
    except (Exception, SystemExit) as e:  # nothing to record it on: the worker says it (decision 54, item 8: by the
        # one rule), also what connect() refuses, such as a schema version another program's init brought
        say(error="connection to the target lost" if lost(e) else reason_line(target_secrets(), e, "claiming"))
        raise SystemExit(1) from None
    if t is None:
        return
    say(claimed=t["name"], run=t["run"], max_seconds=t["max_seconds"])
    try:
        answer = load(conn, t)
    except BaseException as e:  # everything, so no unscrubbed traceback reaches stderr (open point F4)
        answer = {"reason": reason_line(t.get("values", []), e, t.get("step", "claiming"), t.get("source_table"),
                                       t.get("source"))}
    if "reason" in answer:  # outside the except, so a failing fail() cannot print the unscrubbed error with it
        try:
            answer = fail(conn, t, answer["reason"])
        except Exception:  # the target dropped the connection: the lock went with it, nothing can be stored
            answer = {"status": "failed", "reason": "connection to the target lost"}
    say(table=t["name"], **answer)
    conn.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
