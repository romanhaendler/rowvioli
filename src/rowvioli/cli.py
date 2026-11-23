"""The commands: arguments, the answer on stdout, the exit code."""
import argparse
import errno
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
    sub.add_parser("key", help="create a key pair").add_argument(
        "action", choices=["new"], help="new: write worker.key (private, keep it secret) and worker.pub here")
    lp = sub.add_parser("list", help="print the tables of a source")
    lp.add_argument("source")
    lp.add_argument("--definition", help="directory of the definition (default: sources here; without it, the target)")
    ap = sub.add_parser("apply", help="write the definition into the target")
    ap.add_argument("directory", nargs="?", default="sources", help="directory of the definition (default: sources)")
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
    except adbc.Error as e:  # the target refused or is unreachable: its message in one line, not a traceback
        stop(work.plain(load.reason_line(load.target_secrets(), e, "asking the target")))
    except SystemExit as e:
        if not isinstance(e.code, str):
            raise
        stop(e.code)


def stop(message):
    """Ends with the message on stderr and exit code 1, as SystemExit(message) does, but written by out(): Python's own
    write stays in stderr's buffer, where a broken pipe fails it again at shutdown and makes the exit code 120."""
    work.out(message + "\n")
    raise SystemExit(1)


def command(a):
    from_target = a.command == "list" and a.definition is None and not Path("sources").is_dir()
    if from_target and not os.environ.get("ROWVIOLI_TARGET_URL"):
        raise SystemExit("list reads the source from a definition directory (sources/ here, or --definition <dir>) "
                         "or from the target (ROWVIOLI_TARGET_URL and the key file); neither is here")
    needs = {"init": ["ROWVIOLI_TARGET_URL"], "status": ["ROWVIOLI_TARGET_URL"],
             "run": ["ROWVIOLI_TARGET_URL"], "work": ["ROWVIOLI_TARGET_URL"]}
    missing = [v for v in needs.get(a.command, []) if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set")
    if a.command in needs or from_target:
        target.check_address(os.environ["ROWVIOLI_TARGET_URL"])  # before the key file: it is the first slip to fix
    if a.command in ("run", "work") or from_target:  # one place for the default; the run processes inherit the absolute path
        key = os.path.abspath(os.environ.get("ROWVIOLI_KEY_FILE") or "worker.key")
        try:
            open(key, "rb").close()  # opened, not just looked for: a directory or an unreadable file stops here too
        except OSError as e:
            raise SystemExit(f"the key file {key}: {e.strerror}" + (
                "; copy worker.key from where `rowvioli key new` was run (only for a new target does "
                "`rowvioli key new` create it)" if e.errno == errno.ENOENT else ""))
        os.environ["ROWVIOLI_KEY_FILE"] = key
    if a.command == "init":
        target.connect(init=True)
        print("the schema _rowvioli is ready in the target")
    elif a.command == "key":
        seal.new_key()
        print("created worker.key (keep it secret) and worker.pub")
    elif a.command == "apply" and a.directory == "sources" and not Path("sources").is_dir():
        raise SystemExit(f"{Path('sources').resolve()} does not exist; `rowvioli apply <directory>` takes another")
    elif a.command == "apply" and a.check:
        definition.read(a.directory)
        print("the definition is valid")
    elif a.command == "apply":
        apply.apply(a.directory, a.key or str(Path(a.directory).resolve().parent / "worker.pub"), a.init)
    elif a.command == "list":
        print_tables(None if from_target else a.definition or "sources", a.source)
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
        # every cell: a name applied by an older version may hold a control character too
        lines.append([work.plain(c) for c in (src, name, target_name, definition.duration(max_age),
                      "" if age is None else definition.duration(age),
                      "now" if wait is None else "in " + definition.duration(wait), status, reason or "")])
    widths = [max(len(line[i]) for line in lines) for i in range(7)]
    for line in lines:
        print(("  ".join(c.ljust(w) for c, w in zip(line, widths)) + "  " + line[7]).rstrip())


def shown(text):
    """A message for a terminal: control characters as `?`, line breaks kept."""
    return "\n".join(map(work.plain, text.split("\n")))


def print_tables(directory, name):
    """The tables of a source from its connector's `tables`, as lines for the source's tables block."""
    if directory is None:  # no definition here: the connection `apply` stored in the target, opened with the worker key
        row = target.sql(target.connect(), "SELECT type, connection, key_id FROM _rowvioli.sources "
                         "WHERE name = $1", [name])
        if not row:
            raise SystemExit(f"the target has no source {name}; `rowvioli apply` puts it there "
                             "(a source may be applied with an empty tables block first)")
        try:
            s = {"type": row[0][0], "connection": seal.unseal(os.environ["ROWVIOLI_KEY_FILE"], row[0][2], name, row[0][1])}
        except Exception as e:
            raise SystemExit(shown(f"the connection of source {name} cannot be decrypted: {e}"))
    else:
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
        readable = ("path",) if s["type"] == "file" else ()  # a directory is no secret (as in a run)
        values = load.connection_values(s["connection"], readable)
        if isinstance(e, KeyError) and e.args and isinstance(e.args[0], str) and e.args[0] not in s["connection"]:
            raise SystemExit(shown(load.scrub(values, f"the connection of source {name} has no {e.args[0]}")))
        raise SystemExit(shown(load.scrub(values, str(e) or type(e).__name__)))
    for table, key in tables.items():
        # a JSON string and a JSON list of strings are TOML as well
        print(f"{json.dumps(table)} = {{ key = {json.dumps(key)} }}" if key else f"{json.dumps(table)} = {{}}")
