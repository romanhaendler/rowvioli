"""The worker loop of `run` and `work`: ask what is claimable, start a fresh process per run."""
import json
import math
import os
import queue
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

MASCOT = """\
  .~~~~~~~.   .~~~~~~~.
  { o   o }   { o   o }
  {   v   }---{   v   }
  '~~~~~~~'   '~~~~~~~'
    |   |       |   |"""


def say(text):
    """One line on stderr: local date and time to the second, a space, the text. Nothing but scrubbed text."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}", file=sys.stderr, flush=True)


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
        if sys.stderr.isatty():
            print(MASCOT, file=sys.stderr, flush=True)
        say(f"worker {worker} started with {slots} slots on {sql(conn, 'SELECT current_database()')[0][0]}")
    while True:
        try:
            conn = conn or target.connect()
            while ended:
                record(conn, ended[0])
                ended.pop(0)
            claimable, busy = sql(conn, CLAIMABLE_AND_BUSY, [source, table])[0]
        except adbc.Error as e:  # the target is unreachable: try again in two seconds (open point E11)
            if once:
                raise
            if conn:
                say("the target is unreachable, connecting again every two seconds: "
                + load.scrub(load.target_secrets(), str(e)))
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


def say_end(claim, outcome, text):
    say(f"{claim['claimed']} {outcome} after {time.monotonic() - claim['started']:.1f}s: {text}")


def listen(runs, answers, ended, seconds, lines):
    """Reads what the run processes say, for `seconds` or until one ends, and kills a run that exceeds its
    `max_seconds`; its claim goes to `ended`. Returns True if one died before it claimed anything."""
    end = time.monotonic() + seconds
    while (now := time.monotonic()) < end:
        for p, claim in runs.items():
            if claim and claim["deadline"] <= now:
                p.kill()  # docs/target.md "Order when finishing": kill first, write the reason afterwards
                claim["deadline"], claim["reason"] = math.inf, f"ended after max_seconds = {claim['max_seconds']}"
                say_end(claim, "failed", claim["reason"])
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
                say(f"{said['claimed']} started, run {said['run']}")
            elif "answer" not in runs[p]:  # a run killed after max_seconds may still have answered
                answers[said.pop("table")] = runs[p]["answer"] = said
                if said["status"] == "ok":
                    say_end(runs[p], "ok", f"{said['inserted']} inserted, {said['updated']} updated, "
                                           f"{said['deleted']} deleted")
                else:
                    say_end(runs[p], "failed", said["reason"])
                runs[p]["deadline"] = math.inf
            continue
        p.wait()  # end of its output: the process has ended
        claim = runs.pop(p)
        if claim and "answer" not in claim:  # it died after its claim, e.g. kill -9
            answers[claim["claimed"]] = {"status": "failed", "reason": "worker lost"}
            say_end(claim, "failed", "worker lost")
        if claim is None and p.returncode != 0:
            say(f"a run process ended with exit code {p.returncode} before it claimed anything")
        return claim is None and p.returncode != 0
    return False


def record(conn, claim):
    """The reason of a run killed after max_seconds, on the run and its table, if the run is still running."""
    sql(conn, """WITH r AS (UPDATE _rowvioli.runs SET status = 'failed', finished_at = clock_timestamp(), reason = $2
                             WHERE run = $1 AND status = 'running' RETURNING "table")
                 UPDATE _rowvioli.tables SET reason = $2 WHERE id IN (SELECT "table" FROM r)""",
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
        conn.close()
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
