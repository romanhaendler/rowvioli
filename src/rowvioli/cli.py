"""The commands: arguments, the answer on stdout, the exit code."""
import argparse
import importlib.metadata
import json
import os
import sys
import time
from pathlib import Path

import adbc_driver_postgresql.dbapi as adbc

from . import apply, contract, definition, load, seal, target, work


def main():
    p = argparse.ArgumentParser(prog="rowvioli")
    p.add_argument("--version", action="version", version=importlib.metadata.version("rowvioli"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the schema _rowvioli in the target")
    sub.add_parser("key", help="create a key pair").add_argument("action", choices=["new"])
    lp = sub.add_parser("list", help="print the tables of a source")
    lp.add_argument("source")
    lp.add_argument("--definition", default="sources", help="directory of the definition")
    ap = sub.add_parser("apply", help="write the definition into the target")
    ap.add_argument("directory")
    ap.add_argument("--check", action="store_true", help="only read and check the definition")
    ap.add_argument("--init", action="store_true", help="create the schema _rowvioli first if it is missing")
    ap.add_argument("--key", help="public key file (default: worker.pub next to the directory)")
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
        raise SystemExit(load.scrub(load.target_secrets(), str(e)))


def command(a):
    needs = {"init": ["ROWVIOLI_TARGET_URL"], "status": ["ROWVIOLI_TARGET_URL"],
             "run": ["ROWVIOLI_TARGET_URL", "ROWVIOLI_KEY_FILE"], "work": ["ROWVIOLI_TARGET_URL", "ROWVIOLI_KEY_FILE"]}
    missing = [v for v in needs.get(a.command, []) if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set")
    if a.command == "init":
        target.connect(init=True)
        print("the schema _rowvioli is ready in the target")
    elif a.command == "key":
        seal.new_key()
        print("created worker.key (keep it secret) and worker.pub")
    elif a.command == "apply" and a.check:
        definition.read(a.directory)
        print("the definition is valid")
    elif a.command == "apply":
        apply.apply(a.directory, a.key or str(Path(a.directory).resolve().parent / "worker.pub"), a.init)
    elif a.command == "list":
        print_tables(a.definition, a.source)
    elif a.command == "status":
        print_status(a.source or "", a.table or "")
    elif a.command in ("run", "work"):
        if a.command == "work":
            work.loop(a.slots)
            return
        started = time.monotonic()
        answers, crashed = work.run(a.source or "", a.table or "", a.slots)
        if not answers and not a.source:
            work.say_waiting()
        print(json.dumps({"seconds": round(time.monotonic() - started, 1), "tables": answers}))
        sys.exit(1 if crashed or any(answer["status"] != "ok" for answer in answers.values()) else 0)


STATUS = f"""SELECT source, source_table, target_table, extract(epoch FROM max_age)::bigint,
       extract(epoch FROM age)::bigint,
       CASE WHEN due_at <= now() THEN NULL ELSE ceil(extract(epoch FROM due_at - now()))::bigint END,
       status, reason, rows_written, rows_last_run
  FROM _rowvioli.status
 WHERE {work.SCOPE}
 ORDER BY source, source_table"""


def print_status(source, table):
    """The status view as an aligned table. It formats; status, due time and progress are the view's."""
    conn = target.connect(versioned=False)
    lines = [["source", "table", "target", "max_age", "age", "due", "status", "reason"]]
    for src, name, target_name, max_age, age, wait, status, reason, written, last in target.sql(
            conn, STATUS, [source, table]):
        if status == "loading":  # progress in place of a reason, none yet: no reason
            reason = "" if written is None else f"{written:,} of about {last:,} rows" if last else f"{written:,} rows"
        lines.append([src, name, target_name, definition.duration(max_age),
                      "" if age is None else definition.duration(age),
                      "now" if wait is None else "in " + definition.duration(wait), status, reason or ""])
    widths = [max(len(line[i]) for line in lines) for i in range(7)]
    for line in lines:
        print(("  ".join(c.ljust(w) for c, w in zip(line, widths)) + "  " + line[7]).rstrip())


def print_tables(directory, name):
    """The tables of a source from its connector's `tables`, as lines for the source's tables block."""
    sources, _, _ = definition.read(directory, os.environ, only=name)
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
