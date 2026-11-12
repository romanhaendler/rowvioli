"""The commands: arguments, the answer on stdout, the exit code."""
import argparse
import json
import os
import sys
import time

import adbc_driver_postgresql.dbapi as adbc

from . import apply, contract, definition, load, seal, target, work


def main():
    p = argparse.ArgumentParser(prog="rowvioli")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the schema _rowvioli in the target")
    sub.add_parser("key", help="create a key pair").add_argument("action", choices=["new"])
    lp = sub.add_parser("list", help="print the tables of a source")
    lp.add_argument("source")
    lp.add_argument("--definition", default="sources", help="directory of the definition")
    ap = sub.add_parser("apply", help="write the definition into the target")
    ap.add_argument("directory")
    ap.add_argument("--check", action="store_true", help="only read and check the definition")
    ap.add_argument("--key", default="worker.pub", help="public key file")
    rp = sub.add_parser("run", help="load what is due, once")
    rp.add_argument("source", nargs="?")
    rp.add_argument("table", nargs="?")
    rp.add_argument("--slots", type=int, default=4)
    sp = sub.add_parser("status", help="print the state of the enabled tables")
    sp.add_argument("source", nargs="?")
    sp.add_argument("table", nargs="?")
    sub.add_parser("work", help="load what is due, permanently").add_argument("--slots", type=int, default=4)
    a = p.parse_args()
    if getattr(a, "slots", 1) < 1:  # with no slot `run` would wait forever for what is due
        p.error("--slots must be at least 1")
    try:
        command(a)
    except adbc.Error as e:  # the target refused or is unreachable: its message, not a traceback
        raise SystemExit(load.scrub(load.connection_values(os.environ.get("ROWVIOLI_TARGET_URL")), str(e)))


def command(a):
    if a.command == "init":
        target.connect(init=True)
    elif a.command == "key":
        seal.new_key()
    elif a.command == "apply" and a.check:
        definition.read(a.directory)
        print("the definition is valid")
    elif a.command == "apply":
        apply.apply(a.directory, a.key)
    elif a.command == "list":
        print_tables(a.definition, a.source)
    elif a.command == "status":
        print_status(a.source or "", a.table or "")
    elif a.command in ("run", "work"):
        if not os.environ.get("ROWVIOLI_KEY_FILE"):  # ROWVIOLI_TARGET_URL is checked when connecting
            raise SystemExit("ROWVIOLI_KEY_FILE is not set")
        if a.command == "work":
            work.loop(a.slots)
            return
        started = time.monotonic()
        answers, crashed = work.run(a.source or "", a.table or "", a.slots)
        print(json.dumps({"seconds": round(time.monotonic() - started, 1), "tables": answers}))
        sys.exit(1 if crashed or any(answer["status"] != "ok" for answer in answers.values()) else 0)


STATUS = f"""SELECT source, source_table, extract(epoch FROM max_age)::bigint, extract(epoch FROM age)::bigint,
       CASE WHEN due_at <= now() THEN NULL ELSE ceil(extract(epoch FROM due_at - now()))::bigint END,
       status, reason, rows_written, rows_last_run
  FROM _rowvioli.status
 WHERE {work.SCOPE}
 ORDER BY source, source_table"""


def print_status(source, table):
    """The status view as an aligned table. It formats; status, due time and progress are the view's."""
    conn = target.connect(versioned=False)
    lines = [["source", "table", "max_age", "age", "due", "status", "reason"]]
    for src, name, max_age, age, wait, status, reason, written, last in target.sql(conn, STATUS, [source, table]):
        if status == "loading":  # progress in place of a reason, none yet: no reason
            reason = "" if written is None else f"{written:,} of about {last:,} rows" if last else f"{written:,} rows"
        lines.append([src, name, definition.duration(max_age), "" if age is None else definition.duration(age),
                      "now" if wait is None else "in " + definition.duration(wait), status, reason or ""])
    widths = [max(len(line[i]) for line in lines) for i in range(6)]
    for line in lines:
        print(("  ".join(c.ljust(w) for c, w in zip(line, widths)) + "  " + line[6]).rstrip())


def print_tables(directory, name):
    """The tables of a source from its connector's `tables`, as lines for the source's tables block."""
    sources, _, _ = definition.read(directory, os.environ)
    s = next((s for s in sources if s["name"] == name), None)
    if s is None:
        raise SystemExit(f"{directory} has no source {name}")
    connector = contract.connector(s["type"])
    if not hasattr(connector, "tables"):
        raise SystemExit(f"connector {s['type']} of source {name} cannot list tables")
    try:
        tables = connector.tables(s["connection"])
    except Exception as e:  # a driver may quote the connection in its message
        raise SystemExit(load.scrub(load.connection_values(s["connection"]), str(e) or type(e).__name__))
    for table, key in tables.items():
        # a JSON string and a JSON list of strings are TOML as well
        print(f"{json.dumps(table)} = {{ key = {json.dumps(key)} }}" if key else f"{json.dumps(table)} = {{}}")
