"""The worker loop shared by `run` and `work` (spec "Worker loop and claim"): a fresh process per run."""
import json
import os
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


def loop(slots, source="", table="", once=False):
    """Starts a run process per due table, up to `slots` at a time. With `once` it returns when nothing in
    scope is due or loading, with the answers of its runs as {target table: answer}."""
    worker = f"{socket.gethostname()}:{os.getpid()}"
    answers, running = {}, []
    with control.connect() as conn:
        while True:
            for p in [p for p in running if p.poll() is not None]:
                running.remove(p)
                for line in p.stdout.read().splitlines():
                    a = json.loads(line)
                    answers[a.pop("table")] = a
            due, loading = sql(conn, DUE, [source, table])[0]
            if once and not (due or loading or running):
                return answers
            for _ in range(min(due, slots - len(running))):
                running.append(subprocess.Popen([sys.executable, "-m", "rowvioli", "_load", worker, source, table],
                                                stdout=subprocess.PIPE, text=True))
            # ask again every two seconds, or as soon as a run ends
            end = time.monotonic() + 2
            while time.monotonic() < end and all(p.poll() is None for p in running):
                time.sleep(0.05)


def run(source="", table="", slots=4):
    """`rowvioli run [source [table]]`: naming something requests it, then loads until nothing in scope is due."""
    start = time.monotonic()
    if source:
        with control.connect() as conn:
            sql(conn, f"UPDATE _rowvioli.tables SET requested_at = now() WHERE {SCOPE}", [source, table])
    answers = loop(slots, source, table, once=True)
    print(json.dumps({"seconds": round(time.monotonic() - start, 1), "tables": answers}))
    return 1 if any(a["status"] != "ok" for a in answers.values()) else 0
