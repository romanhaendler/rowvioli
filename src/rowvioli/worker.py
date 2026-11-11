"""The worker loop shared by `run` and `work` (spec "Worker loop and claim"): a fresh process per run."""
import json
import os
import select
import socket
import subprocess
import sys
import time

from . import control
from .control import sql

SCOPE = "($1::text = '' OR source = $1::text) AND ($2::text = '' OR source_table = $2::text)"
DUE = f"""SELECT count(*) FILTER (WHERE status <> 'loading' AND due_at <= now()),
                 count(*) FILTER (WHERE status = 'loading')
            FROM _rowvioli.status WHERE {SCOPE}"""

# the worker ends a hanging run's process and records why, unless the run finished meanwhile
END = """WITH r AS (UPDATE _rowvioli.runs SET status = 'failed', finished_at = clock_timestamp(), reason = $2
                    WHERE run = $1 AND status = 'running' RETURNING "table")
         UPDATE _rowvioli.tables t SET reason = $2 FROM r WHERE t.id = r."table\""""


def loop(slots, source="", table="", once=False):
    """Starts a run process per due table, up to `slots` at a time, and ends those that exceed `max_seconds`.
    With `once` it returns when nothing in scope is due or loading, as ({target table: answer}, crashed).
    `crashed`: a run process died before claiming; `once` then starts no more, so it cannot loop forever."""
    worker = f"{socket.gethostname()}:{os.getpid()}"
    answers, running, crashed = {}, {}, False  # running: process -> its claim line, {} until it claimed
    with control.connect() as conn:
        while True:
            for p, c in running.items():
                if c and p.poll() is None and time.monotonic() > c["at"] + c["max_seconds"]:
                    p.kill()
                    p.wait()
                    reason = f"ended by worker {worker} after max_seconds = {c['max_seconds']}"
                    sql(conn, END, [c["run"], reason])
                    answers[c["claimed"]] = {"status": "failed", "reason": reason}
                    c["done"] = True
            due, loading = sql(conn, DUE, [source, table])[0]
            if once and not running and (crashed or not (due or loading)):
                return answers, crashed
            for _ in range(0 if once and crashed else min(due, slots - len(running))):
                p = subprocess.Popen([sys.executable, "-m", "rowvioli", "_load", worker, source, table],
                                     stdout=subprocess.PIPE, text=True)
                running[p] = {}
            # ask again every two seconds, or as soon as a run that claimed something ends
            end, ended = time.monotonic() + 2, False
            while not ended and (left := end - time.monotonic()) > 0:
                readable, _, _ = select.select([p.stdout for p in running], [], [], left)
                for p in [p for p in running if p.stdout in readable]:
                    if line := p.stdout.readline():
                        a = json.loads(line)
                        if "claimed" in a:
                            running[p] = {**a, "at": time.monotonic()}
                        else:
                            answers[a.pop("table")] = a
                            running[p]["done"] = True
                    else:  # end of output: the process has ended
                        p.wait()
                        claimed = running.pop(p)
                        if claimed and not claimed.get("done"):  # it died without an answer, e.g. kill -9
                            answers[claimed["claimed"]] = {"status": "failed", "reason": "worker lost"}
                        crashed |= not claimed and p.returncode != 0
                        ended |= bool(claimed)


def run(source="", table="", slots=4):
    """`rowvioli run [source [table]]`: naming something requests it, then loads until nothing in scope is due."""
    start = time.monotonic()
    if source:
        with control.connect() as conn:
            sql(conn, f"UPDATE _rowvioli.tables SET requested_at = now() WHERE {SCOPE}", [source, table])
    answers, crashed = loop(slots, source, table, once=True)
    print(json.dumps({"seconds": round(time.monotonic() - start, 1), "tables": answers}))
    return 1 if crashed or any(a["status"] != "ok" for a in answers.values()) else 0
