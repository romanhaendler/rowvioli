"""The worker loop of `run` and `work`: ask what is claimable, start a fresh process per run."""
import json
import math
import os
import select
import socket
import subprocess
import sys
import time

from . import target
from .target import CLAIMABLE, sql

SCOPE = "($1::text = '' OR source = $1::text) AND ($2::text = '' OR source_table = $2::text)"
# how many runs may start now, and whether anything in scope is due or loading
ASK = f"""SELECT (SELECT count(*) FROM ({CLAIMABLE}) c), count(*) FILTER (WHERE status = 'loading' OR due_at <= now())
            FROM _rowvioli.status WHERE {SCOPE}"""


def loop(slots, source="", table="", once=False):
    """Every two seconds, or as soon as a run process ends, asks what in scope is claimable and starts a run
    process for each, up to `slots` at a time. With `once` it returns ({target table: answer}, crashed) when
    nothing in scope is due or loading. `crashed`: a run process died before it claimed anything; `once` then
    starts no more, so it cannot start processes forever."""
    worker = f"{socket.gethostname()}:{os.getpid()}"
    answers, runs, crashed = {}, {}, False  # runs: process -> what it said after its claim, None until then
    ended = []  # runs killed after max_seconds whose reason is not yet recorded
    conn = target.connect()
    while True:
        while ended:
            record(conn, ended[0])
            ended.pop(0)
        claimable, busy = sql(conn, ASK, [source, table])[0]
        if once and not runs and (crashed or not busy):
            conn.close()
            return answers, crashed
        for _ in range(0 if once and crashed else min(claimable, slots - len(runs))):
            runs[subprocess.Popen([sys.executable, "-m", "rowvioli.load", worker, source, table],
                                  stdout=subprocess.PIPE, text=True)] = None
        crashed |= listen(runs, answers, ended, 2)


def listen(runs, answers, ended, seconds):
    """Reads what the run processes say, for `seconds` or until one ends, and kills a run that exceeds its
    `max_seconds`; its claim goes to `ended`. Returns True if one died before it claimed anything."""
    end = time.monotonic() + seconds
    while (now := time.monotonic()) < end:
        for p, claim in runs.items():
            if claim and claim["deadline"] <= now:
                p.kill()  # README "Order when finishing": kill first, write the reason afterwards
                claim["deadline"], claim["reason"] = math.inf, f"ended after max_seconds = {claim['max_seconds']}"
                answers[claim["claimed"]] = claim["answer"] = {"status": "failed", "reason": claim["reason"]}
                ended.append(claim)
        wake = min([end] + [c["deadline"] for c in runs.values() if c])
        readable, _, _ = select.select([p.stdout for p in runs], [], [], wake - now)
        for p in [p for p in runs if p.stdout in readable]:
            if line := p.stdout.readline():
                said = json.loads(line)
                if "claimed" in said:  # the clock for max_seconds starts here
                    runs[p] = said | {"deadline": time.monotonic() + said["max_seconds"]}
                else:
                    answers[said.pop("table")] = runs[p]["answer"] = said
                    runs[p]["deadline"] = math.inf
                continue
            p.wait()  # end of its output: the process has ended
            claim = runs.pop(p)
            if claim and "answer" not in claim:  # it died after its claim, e.g. kill -9
                answers[claim["claimed"]] = {"status": "failed", "reason": "worker lost"}
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
    due or loading. Prints the answer and returns the exit code."""
    started = time.monotonic()
    if source:
        conn = target.connect()
        requested = sql(conn, f"""UPDATE _rowvioli.tables SET requested_at = now()
                                   WHERE id IN (SELECT id FROM _rowvioli.status WHERE {SCOPE}) RETURNING id""",
                        [source, table])
        conn.close()
        if not requested:
            raise SystemExit(f"{source} {table}".strip() + ": no enabled table has this name")
    answers, crashed = loop(slots, source, table, once=True)
    print(json.dumps({"seconds": round(time.monotonic() - started, 1), "tables": answers}))
    return 1 if crashed or any(a["status"] != "ok" for a in answers.values()) else 0
