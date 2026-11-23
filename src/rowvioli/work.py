"""The worker loop of `run` and `work`: ask what is claimable, start a fresh process per run."""
import json
import math
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime

import adbc_driver_postgresql.dbapi as adbc

from . import load, target
from .target import CLAIMABLE, sql

SCOPE = "($1::text = '' OR source = $1::text) AND ($2::text = '' OR source_table = $2::text)"
# how many runs may start now, and whether anything in scope is due or loading
CLAIMABLE_AND_BUSY = f"""SELECT (SELECT count(*) FROM ({CLAIMABLE}) c),
                                count(*) FILTER (WHERE status = 'loading' OR due_at <= now())
                           FROM _rowvioli.status WHERE {SCOPE}"""
# of the given runs, those whose table is no longer loading: their lock went with their connection (decision 7)
LOST = """SELECT r.run FROM _rowvioli.runs r JOIN _rowvioli.status s ON s.id = r."table"
           WHERE r.run = ANY(string_to_array($1, ',')::bigint[]) AND s.status <> 'loading'"""

MASCOT = """\
.----.     .~~~~~~~.     .~~~~~~~.     .~~~~~~~.     .----.
|####|     { o   o }     { o   o }     { o   o }     |    |
|####|-[#]-{   v   }-[#]-{   v   }-[#]-{   v   }-[#]-|    |
|####|     '~~~~~~~'     '~~~~~~~'     '~~~~~~~'     |####|
'----'       |   |         |   |         |   |       '----'"""


COLOURS = {"✔": "32", "✘": "31", "⚠": "33"}


def colour():
    """Whether the lines are coloured: wherever stderr goes, a pipe or a file too, unless NO_COLOR is set,
    TERM is dumb, or stderr is the systemd journal."""
    # shortcut: the legacy Windows console prints escape codes as text (NO_COLOR=1 helps), upgrade if someone asks
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:  # JOURNAL_STREAM is inherited by children, so only stderr's own device and inode mean the journal
        s = os.fstat(sys.stderr.fileno())
    except (AttributeError, OSError, ValueError):
        return False
    return os.environ.get("JOURNAL_STREAM") != f"{s.st_dev}:{s.st_ino}"


def out(text):
    """Writes to stderr. Output never ends the worker: without a stderr, or with a closed one, the text is lost.
    A mark stderr cannot encode comes out as \\u2714: Python writes stderr with backslashreplace."""
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        sys.stderr = None  # else Python fails again flushing the unflushed data at shutdown: exit code 120


def plain(text):
    """The text with every control character (C0, DEL, C1) as `?`: a table name or a reason quoting source data
    cannot clear the screen, set the title or forge a line."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", "?", text)  # 2028, 2029: splitlines() splits there


def say(text, mark=""):
    """One line on stderr: local date and time to the second, a mark or a space, the text. Nothing but scrubbed
    text. The same line everywhere; colour() adds colour."""
    when, body = time.strftime("%Y-%m-%d %H:%M:%S"), f"{mark or ' '} {plain(text)}"
    if colour():
        when, body = f"\033[2m{when}\033[0m", f"\033[{COLOURS[mark]}m{body}\033[0m" if mark in COLOURS else body
    out(f"{when} {body}\n")


def loop(slots, source="", table="", once=False):
    """Every two seconds, or as soon as a run process ends, asks what in scope is claimable and starts a run
    process for each, up to `slots` at a time. With `once` it returns ({target table: answer}, crashed) when
    nothing in scope is due or loading. `crashed`: a run process died before it claimed anything; `once` then
    starts no more, so it cannot start processes forever. Without `once`, SIGTERM (Ctrl+Break on Windows) makes it
    start nothing new and return once its runs have ended (decision 33)."""
    worker = f"{socket.gethostname()}:{os.getpid()}"
    answers, runs, crashed = {}, {}, False  # runs: process -> what it said after its claim, None until then
    ended = []  # runs killed after max_seconds whose reason is not yet recorded
    stopping = []
    lines = queue.Queue()  # what the run processes say, from one reader thread each
    if not once:
        for name in ("SIGTERM", "SIGBREAK"):  # Windows never delivers SIGTERM; Ctrl+Break is its stop signal
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda *_: stopping.append(True))
    conn = target.connect()
    stopped = False
    if not once:
        if sys.stderr and sys.stderr.isatty():
            out(MASCOT + "\n")
        say(f"worker {worker} started with {slots} slots on {sql(conn, 'SELECT current_database()')[0][0]}")
    while True:
        try:
            conn = conn or target.connect()
            while ended:
                record(conn, ended[0])
                ended.pop(0)
            claimable, busy = sql(conn, CLAIMABLE_AND_BUSY, [source, table])[0]
            end_lost(conn, runs)
        except adbc.Error as e:  # the target is unreachable: try again in two seconds (open point E11)
            if once:
                raise
            if conn:
                say("the target is unreachable, connecting again every two seconds: "
                    + load.reason_line(load.target_secrets(), e, "asking the target"), "⚠")
            conn, claimable = None, 0
        if stopping and not stopped:
            stopped = True
            say(f"stopping, {len(runs)} run{' finishes' if len(runs) == 1 else 's finish'}")
        if (once and not runs and (crashed or not busy)) or (stopping and not runs):
            if conn:
                conn.close()
            return answers, crashed
        for _ in range(0 if stopping or (once and crashed) else min(claimable, slots - len(runs))):
            p = subprocess.Popen([sys.executable, "-m", "rowvioli.load", worker, source, table],
                                 # nothing unscrubbed on stderr: a driver may print a connection value there
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 stdin=subprocess.PIPE)  # ends with the worker: the run's sign of its death
            runs[p] = None
            threading.Thread(target=pump, args=(p, lines), daemon=True).start()
        crashed |= listen(runs, answers, ended, 2, lines)


def pump(p, lines):
    """Hands every line a run process says to `lines`, then "" at its end. select() cannot wait on pipes on Windows."""
    try:
        for line in p.stdout:
            lines.put((p, line))
    finally:
        lines.put((p, ""))  # without the end marker the run would hold its slot for good


def say_run(claim, outcome, text):
    """A run's line: its target table, `started`, `ok` or `failed`, the seconds since its claim, the text."""
    secs = "" if outcome == "started" else f"{time.monotonic() - claim['started']:.1f}s"
    say(f"{claim['claimed']:<28} {outcome:<7} {secs:>8}  {text}", {"started": "▶", "ok": "✔"}.get(outcome, "✘"))


def listen(runs, answers, ended, seconds, lines):
    """Reads what the run processes say, for `seconds` or until one ends, and kills a run that exceeds its
    `max_seconds`; its claim goes to `ended`. Returns True if one died before it claimed anything."""
    end = time.monotonic() + seconds
    while (now := time.monotonic()) < end:
        for p, claim in runs.items():
            if claim and claim["deadline"] <= now:
                p.kill()  # docs/target.md "Order when finishing": kill first, write the reason afterwards
                claim["deadline"], claim["reason"] = math.inf, f"ended after max_seconds = {claim['max_seconds']}"
                say_run(claim, "failed", claim["reason"])
                answers[claim["claimed"]] = claim["answer"] = {"status": "failed", "reason": claim["reason"]}
                ended.append(claim)
        wake = min([end] + [c["deadline"] for c in runs.values() if c])
        try:
            p, line = lines.get(timeout=max(0, wake - now))
        except queue.Empty:
            continue
        if line:
            said = json.loads(line)
            if "claimed" in said:  # the clock for max_seconds starts here
                runs[p] = said | {"deadline": time.monotonic() + said["max_seconds"], "started": time.monotonic()}
                say_run(runs[p], "started", f"run {said['run']}")
            elif "answer" not in runs[p]:  # a run killed after max_seconds may still have answered
                answers[said.pop("table")] = runs[p]["answer"] = said
                if said.get("reason") == "connection to the target lost":  # the run could not record it itself
                    ended.append(runs[p] | {"reason": said["reason"]})
                if said["status"] == "ok":
                    say_run(runs[p], "ok", f"+{said['inserted']} ~{said['updated']} -{said['deleted']}")
                else:
                    say_run(runs[p], "failed", said["reason"])
                runs[p]["deadline"] = math.inf
            continue
        p.wait()  # end of its output: the process has ended
        claim = runs.pop(p)
        if claim and "answer" not in claim:  # it died after its claim, e.g. kill -9, or end_lost killed it
            answers[claim["claimed"]] = {"status": "failed", "reason": claim.get("reason", "worker lost")}
            say_run(claim, "failed", answers[claim["claimed"]]["reason"])
        if claim is None and p.returncode != 0:
            say(f"a run process ended with exit code {p.returncode} before it claimed anything", "✘")
        return claim is None and p.returncode != 0
    return False


def end_lost(conn, runs):
    """Kills a run whose connection to the target is gone: it notices only at its next statement, which may come
    after a long read of its source, and it can never publish. One that already answered is left to end."""
    waiting = {c["run"]: p for p, c in runs.items() if c and "answer" not in c}
    for (run,) in sql(conn, LOST, [",".join(map(str, waiting))]) if waiting else []:
        runs[waiting[run]]["reason"] = "connection to the target lost"  # said once its output ends
        record(conn, runs[waiting[run]])  # its lock is gone, so it cannot publish any more
        waiting[run].kill()


def record(conn, claim):
    """The reason of a run the worker ended (after max_seconds, or with its target connection lost), on the run and
    its table, if the run is still running. A claim may have closed the row first as `worker lost` once the lock was
    free: the reason the worker knows replaces it, but not on the table, which belongs to that claim's run now."""
    sql(conn, """WITH old AS (SELECT "table", status FROM _rowvioli.runs WHERE run = $1),
                      r AS (UPDATE _rowvioli.runs SET status = 'failed', reason = $2,
                                   finished_at = coalesce(finished_at, clock_timestamp())
                             WHERE run = $1 AND (status = 'running' OR reason = 'worker lost'))
                 UPDATE _rowvioli.tables SET reason = $2
                  WHERE id IN (SELECT "table" FROM old WHERE status = 'running')""",
        [claim["run"], claim["reason"]])


def run(source, table, slots):
    """`rowvioli run [<source> [<table>]]`: naming something requests it, then loads until nothing in scope is
    due or loading. Returns ({target table: answer}, crashed)."""
    if source:
        conn = target.connect()
        requested = sql(conn, f"""UPDATE _rowvioli.tables SET requested_at = now()
                                   WHERE id IN (SELECT id FROM _rowvioli.status WHERE {SCOPE}) RETURNING id""",
                        [source, table])
        like = [] if requested or not table else sql(
            conn, "SELECT source_table FROM _rowvioli.status WHERE source = $1 AND right(source_table, $3::int) = $2::text",
            [source, "." + table, len(table) + 1])
        # a first name that is no source: the person may have given the table, so look for the source that holds it
        is_source = requested or sql(conn, "SELECT 1 FROM _rowvioli.status WHERE source = $1", [source])
        sources = [] if is_source else [r[0] for r in sql(
            conn, "SELECT DISTINCT source FROM _rowvioli.status WHERE right(source_table, $2::int) = $1::text",
            ["." + source, len(source) + 1])]
        row = [] if is_source else sql(conn, "SELECT enabled FROM _rowvioli.sources WHERE name = $1", [source])
        conn.close()
        if row:  # a source of the definition's past or without tables yet: not a mistake in the name
            raise SystemExit(f"{source} has no tables; `rowvioli list {source}` prints them" if row[0][0]
                             else f"{source} is not in the definition any more")
        if not is_source:
            raise SystemExit((f"{source} {table}: " if table else "") + f"{source} is no source: the first name of `run` is a source, the second a table"
                             + (f"; did you mean `rowvioli run {sources[0]} {source}`" if len(sources) == 1 else ""))
        if not requested:
            raise SystemExit(f"{source} {table}".strip() + ": no enabled table has this name"
                             + (f"; did you mean {like[0][0]}" if len(like) == 1 else ""))
    return loop(slots, source, table, once=True)


def say_waiting():
    """`run` without names loaded nothing: if tables wait out the pause after a failure, say so on stderr."""
    conn = target.connect(versioned=False)
    [(n, due)] = sql(conn, "SELECT count(*), min(due_at) FROM _rowvioli.status WHERE status = 'failed' AND due_at > now()")
    conn.close()
    if n:
        due = due.astimezone()
        when = due.strftime("%H:%M:%S" if due.date() == datetime.now().date() else "%Y-%m-%d %H:%M:%S")
        say(f"{n} table{'s wait out their pause' if n > 1 else ' waits out its pause'} after a failure, the first "
            f"until {when}; `rowvioli run <source>` loads them now")
