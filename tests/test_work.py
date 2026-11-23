"""`rowvioli work`, the order of loading, both limits, `max_seconds`, SIGTERM and an unreachable target
(spec tests 9, 10, 11, 13, 14, 19)."""
import fcntl
import os
import pty
import re
import select
import signal
import socket
import subprocess
import sys
import termios
import time
import uuid

import psycopg
import pytest
from rowvioli import work
from conftest import HOST, IMAGE, ROWVIOLI, _query, _wait, until
from test_run import apply, ok, run

COLOUR = {"NO_COLOR": "", "TERM": "xterm", "JOURNAL_STREAM": ""}  # the defaults, whatever the shell has set


# a source view that takes `seconds` per row, to hold a run while it fills the staging table
SLOW = """create function slow(g int, seconds float) returns int language plpgsql
          as $$ begin perform pg_sleep(seconds); return g; end $$"""


def slow(rv, name, rows, seconds):
    rv.source(f"create view {name} as select slow(g, {seconds}) as id from generate_series(1, {rows}) g")


def source(rv, name, settings, tables):
    return f"""
[{name}]
type = "postgres"
max_age = "1h"
{settings}
[{name}.connection]
url = "{rv.source_url}"
[{name}.tables]
{tables}"""


@pytest.fixture
def ready(rv):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    rv.source(SLOW)
    return rv


def test_a_run_that_exceeds_max_seconds_is_ended_and_the_status_shows_why(ready):
    slow(ready, "hanging", 30, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2", '"public.hanging" = { key = ["id"] }'))
    start = time.monotonic()
    code, answer = run(ready)
    assert time.monotonic() - start < 15
    assert code == 1
    failed = answer["tables"]["raw_erp.hanging"]
    assert failed["status"] == "failed" and "max_seconds" in failed["reason"]
    assert ready.target("select status, attempts, reason = %s from _rowvioli.status",
                        [failed["reason"]]) == [("failed", 1, True)]
    assert ready.target("select status, reason = %s, finished_at is not null from _rowvioli.runs",
                        [failed["reason"]]) == [("failed", True, True)]
    assert ready.target("select to_regclass('raw_erp.hanging')") == [(None,)]


def test_a_run_ended_after_max_seconds_keeps_its_reason_when_a_claim_closed_its_row_first(ready):
    slow(ready, "hanging", 30, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2", '"public.hanging" = { key = ["id"] }'))
    p = ready.start("run")
    until(lambda: ready.target("select status from _rowvioli.status") == [("loading",)])
    # what another worker's claim does to a run whose lock it finds free, between the kill and the reason
    ready.target("update _rowvioli.runs set status = 'failed', finished_at = now(), reason = 'worker lost'")
    assert p.wait(timeout=15) == 1
    assert ready.target("select reason from _rowvioli.runs") == [("ended after max_seconds = 2",)]


def test_one_slot_loads_the_tables_in_the_order_of_how_far_they_miss_their_maximum_age(ready):
    for name in ("a", "b", "c"):
        ready.source(f"create table {name} (id int primary key)")
        ready.source(f"insert into {name} values (1)")
    apply(ready, source(ready, "erp", "parallel = 3", '"public.a" = { key = ["id"] }\n'
                        '"public.b" = { key = ["id"], max_age = "10m" }\n"public.c" = { key = ["id"] }'))
    ok(ready)
    # a misses 1h by 1h (1x), b misses 10m by 20m (2x), c misses 1h by 30m (0.5x)
    for name, loaded in (("a", "2 hours"), ("b", "30 minutes"), ("c", "90 minutes")):
        ready.target("update _rowvioli.tables set loaded_at = now() - %s::interval where source_table = %s",
                     [loaded, f"public.{name}"])
    first = ready.target("select max(run) from _rowvioli.runs")[0][0]
    ok(ready, "--slots", "1")
    assert ready.target("select t.source_table from _rowvioli.runs r join _rowvioli.tables t on t.id = r.table "
                        "where r.run > %s order by r.run", [first]) == [("public.b",), ("public.a",), ("public.c",)]


HELD = """select s.name, count(*) from pg_locks l join _rowvioli.sources s on s.id = l.classid::int
           where l.locktype = 'advisory' and l.objsubid = 2 and l.granted and l.classid <> 0
             and l.database = (select oid from pg_database where datname = current_database()) group by s.name"""


def test_several_workers_never_exceed_parallel_per_source_nor_max_running_in_total(ready):
    tables = "\n".join(f'"public.slow{i}" = {{ key = ["id"] }}' for i in range(10))
    for i in range(10):
        slow(ready, f"slow{i}", 4, 0.1)
    apply(ready, source(ready, "erp", "parallel = 2", tables) + source(ready, "crm", "parallel = 3", tables))
    ready.target("update _rowvioli.meta set max_running = 4")
    for _ in range(6):
        ready.start("work", "--slots", "4")
    highest, deadline = {"erp": 0, "crm": 0, "total": 0}, time.monotonic() + 60
    # probe pg_locks every 20 ms until every table was loaded once (experiment 5)
    while ready.target("select count(*) from _rowvioli.status where status <> 'ok'") != [(0,)]:
        assert time.monotonic() < deadline
        held = dict(ready.target(HELD))
        for name, n in [*held.items(), ("total", sum(held.values()))]:
            highest[name] = max(highest[name], n)
        time.sleep(0.02)
    # erp's parallel and max_running were reached, so the probe could have seen them broken
    assert highest["erp"] == 2 and highest["crm"] <= 3 and highest["total"] == 4


def test_run_ends_with_1_when_a_run_process_dies_before_claiming(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    ready.target("alter table _rowvioli.runs add constraint broken check (false) not valid")  # the claim fails
    r = ready.run("run", timeout=20)
    assert r.returncode == 1
    assert ready.target("select status from _rowvioli.status") == [("new",)]


def test_a_tables_max_seconds_overrides_the_sources(ready):
    slow(ready, "patient", 3, 1)
    slow(ready, "hasty", 3, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2\nparallel = 2",
                        '"public.patient" = { key = ["id"], max_seconds = 30 }\n"public.hasty" = { key = ["id"] }'))
    code, answer = run(ready)
    assert answer["tables"]["raw_erp.patient"]["status"] == "ok"
    assert "max_seconds" in answer["tables"]["raw_erp.hasty"]["reason"]


def test_work_on_sigterm_lets_the_run_publish_starts_nothing_new_and_exits_0(ready):
    slow(ready, "first", 3, 1)
    slow(ready, "second", 3, 1)
    apply(ready, source(ready, "erp", "", '"public.first" = { key = ["id"] }\n"public.second" = { key = ["id"] }'))
    worker = ready.start("work", "--slots", "1")
    until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(1,)])
    worker.send_signal(signal.SIGTERM)
    assert worker.wait(timeout=20) == 0
    assert sorted(ready.target("select status from _rowvioli.status")) == [("new",), ("ok",)]
    assert ready.target("select count(*) from _rowvioli.runs") == [(1,)]


def test_with_the_limits_full_the_targets_connections_stay_at_the_running_tables_plus_one_per_worker(ready):
    tables = "\n".join(f'"public.slow{i}" = {{ key = ["id"] }}' for i in range(4))
    for i in range(4):
        slow(ready, f"slow{i}", 30, 1)
    apply(ready, source(ready, "erp", "parallel = 4", tables))
    ready.target("update _rowvioli.meta set max_running = 2")
    for _ in range(3):
        ready.start("work", "--slots", "4")
    until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(2,)])
    connections = """select count(*) from pg_stat_activity
                      where datname = current_database() and pid <> pg_backend_pid()"""
    # the start-up is over when the count has stayed at 2 + 3 for 2 s: run processes started before the first
    # claims committed find nothing and end, and a slow worker may connect late
    # one connection for all the counting: ready.target opens one per query, and on a busy machine the backend of
    # the query before is still closing when the next one counts, which reads as a sixth connection
    with psycopg.connect(ready.target_url, autocommit=True) as counting:
        def count():
            return counting.execute(connections).fetchone()[0]
        stable, deadline, values = time.monotonic(), time.monotonic() + 30, []
        while time.monotonic() - stable < 2:
            values.append(count())
            if values[-1] != 2 + 3:
                stable = time.monotonic()
            assert time.monotonic() < deadline, f"the connections never settled at 5, seen {sorted(set(values))}"
            time.sleep(0.05)
        seen, end = set(), time.monotonic() + 8  # four polling intervals
        while time.monotonic() < end:
            seen.add(count())
            time.sleep(0.02)
    assert seen == {2 + 3}


def test_a_worker_survives_an_unreachable_target_and_loads_again_once_it_accepts_connections(ready):
    ready.source("create table customers (id int primary key)")
    ready.source("insert into customers values (1)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    worker = ready.start("work")
    until(lambda: ready.target("select status from _rowvioli.status") == [("ok",)])
    db = ready.target("select current_database()")[0][0]
    other = ready.target_url.rsplit("/", 1)[0] + "/postgres"
    _query(other, f"alter database {db} allow_connections false")
    _query(other, "select pg_terminate_backend(pid) from pg_stat_activity where datname = %s", [db])
    time.sleep(5)  # more than two of the worker's polling intervals
    assert worker.poll() is None
    _query(other, f"alter database {db} allow_connections true")
    ready.target("update _rowvioli.tables set requested_at = now()")
    until(lambda: ready.target("select count(*) from _rowvioli.runs where status = 'ok'") == [(2,)])


def test_a_run_whose_target_restarts_ends_within_seconds_and_the_table_loads_again(ready):
    """Ticket 11: the run's process waits on its source, not on its dead connection; its worker ends it."""
    name = f"rowvioli-test-{uuid.uuid4().hex[:8]}-restarted"  # the suite's target must not restart
    with socket.socket() as s:  # a fixed port, so that the address survives the restart
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    try:
        subprocess.run(["docker", "run", "-d", "--name", name, "--label", "rowvioli-test", "-e", "POSTGRES_PASSWORD=x",
                        "-p", f"127.0.0.1:{port}:5432", IMAGE], check=True, capture_output=True)
        url = f"postgresql://postgres:x@{HOST}:{port}/postgres"
        _wait(url)
        env = {"ROWVIOLI_TARGET_URL": url}
        assert ready.run("init", env=env).returncode == 0
        ready.source("create table pace (seconds float); insert into pace values (1)")
        ready.source("create view hanging as select slow(g, (select seconds from pace)) as id from generate_series(1, 60) g")
        ready.definition({"erp.toml": source(ready, "erp", "", '"public.hanging" = { key = ["id"] }')})
        assert ready.run("apply", "sources", env=env).returncode == 0
        worker = ready.start("work", env=env)
        until(lambda: _query(url, "select status from _rowvioli.status") == [("loading",)])
        [run] = [int(x) for x in subprocess.run(["pgrep", "-P", str(worker.pid)], capture_output=True,
                                                 text=True).stdout.split()]
        subprocess.run(["docker", "restart", name], check=True, capture_output=True)
        until(lambda: not alive(run), timeout=10)  # the source would hold it for a minute
        _wait(url)
        # the log, runs and the status give the same reason
        lost = "connection to the target lost"
        until(lambda: _query(url, "select status, reason from _rowvioli.runs") == [("failed", lost)])
        assert _query(url, "select status, reason from _rowvioli.status") == [("failed", lost)]
        ready.source("update pace set seconds = 0")  # replacing the view would wait: the source still reads for it
        _query(url, "update _rowvioli.tables set requested_at = now()")  # instead of waiting out the pause
        until(lambda: _query(url, "select status from _rowvioli.status") == [("ok",)], timeout=30)
        assert sorted(_query(url, "select * from raw_erp.hanging")) == sorted(ready.source("select * from hanging"))
        err = said_after_sigterm(worker)
        assert re.search(r"✘ raw_erp\.hanging +failed +\d+\.\ds  connection to the target lost", err), err
        assert "the target is unreachable" in err and "SELECT" not in err, err  # a reason is one line
    finally:
        subprocess.run(["docker", "rm", "-fv", name], capture_output=True)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def said_after_sigterm(worker):
    """What a worker said on stderr, after it was asked to stop."""
    worker.send_signal(signal.SIGTERM)
    assert worker.wait(timeout=20) == 0
    return worker.stderr.read()


def test_work_says_its_start_and_what_it_loads_and_the_counts_equal_those_in_runs(ready):
    ready.source("create table customers (id int primary key)")
    ready.source("insert into customers values (1), (2)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    worker = ready.start("work", "--slots", "3", env=COLOUR)
    until(lambda: ready.target("select status from _rowvioli.status") == [("ok",)])
    db = ready.target("select current_database()")[0][0]
    err = said_after_sigterm(worker)
    assert re.match(rf"\033\[2m\d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d\033\[0m   worker \S+ started with 3 slots on {db}\n", err)
    assert "~~~" not in err  # no mascot when stderr is a pipe
    assert re.search(r"\033\[0m ▶ raw_erp\.customers +started +run 1\n", err)
    [(inserted, updated, deleted)] = ready.target("select inserted, updated, deleted from _rowvioli.runs")
    assert re.search(rf"\033\[0m \033\[32m✔ raw_erp\.customers +ok +\d+\.\ds  \+{inserted} ~{updated} -{deleted}\033\[0m\n",
                     err)
    assert "\r" not in err and not set(work.SPIN) & set(err)  # the status line never reaches a pipe


def test_work_says_a_failure_with_the_reason_of_the_status(ready):
    apply(ready, source(ready, "erp", "", '"public.missing" = { key = ["id"] }'))
    worker = ready.start("work")
    until(lambda: ready.target("select status from _rowvioli.status") == [("failed",)])
    [(reason,)] = ready.target("select reason from _rowvioli.status")
    assert re.search(rf"✘ raw_erp\.missing +failed +\d+\.\ds  {re.escape(reason)}", said_after_sigterm(worker))


def test_work_with_nothing_due_says_only_its_start(ready):
    worker = ready.start("work")
    time.sleep(3)
    err = said_after_sigterm(worker)
    assert " started with " in err
    assert "nothing due" not in err


def test_an_idle_work_on_sigterm_says_stopping_with_0_runs(ready):
    worker = ready.start("work")
    time.sleep(1)
    assert "stopping, 0 runs finish" in said_after_sigterm(worker)


def test_work_on_sigterm_says_stopping_and_the_run_still_says_ok(ready):
    slow(ready, "first", 3, 1)
    apply(ready, source(ready, "erp", "", '"public.first" = { key = ["id"] }'))
    worker = ready.start("work")
    until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(1,)])
    err = said_after_sigterm(worker)
    assert "stopping, 1 run finishes" in err
    assert re.search(r"✔ raw_erp\.first +ok ", err)


def test_a_run_ended_after_max_seconds_gives_a_failure_line(ready):
    slow(ready, "hanging", 30, 1)
    apply(ready, source(ready, "erp", "max_seconds = 2", '"public.hanging" = { key = ["id"] }'))
    assert re.search(r"✘ raw_erp\.hanging +failed +2\.0s  ended after max_seconds = 2", ready.run("run").stderr)


def test_a_run_process_dying_before_its_claim_gives_a_line_with_its_exit_code(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    ready.target("alter table _rowvioli.runs add constraint broken check (false) not valid")
    assert re.search(r"✘ a run process ended with exit code 1 before it claimed", ready.run("run", timeout=20).stderr)


def test_work_shows_the_mascot_before_its_start_line_at_a_terminal(ready):
    master, slave = pty.openpty()
    worker = subprocess.Popen([ROWVIOLI, "work"], cwd=ready.dir, env=ready._env(None), stdout=subprocess.DEVNULL,
                              stderr=slave)
    ready.started.append(worker)
    os.close(slave)
    try:
        out = ""
        while "started with" not in out:
            assert select.select([master], [], [], 10)[0], out
            out += os.read(master, 4096).decode()
        assert ".~~~~~~~.   .~~~~~~~." in out.split("started with")[0]
    finally:
        os.close(master)


def at_a_terminal(ready, env, *until_texts):
    """What a real worker writes to a pseudo-terminal it is the foreground process of, until every one of
    `until_texts` is in it (30 s at most: the status line keeps the terminal busy)."""
    master, slave = pty.openpty()
    worker = subprocess.Popen([ROWVIOLI, "work", "--slots", "4"], cwd=ready.dir, env=ready._env(None) | env,
                              stdout=subprocess.DEVNULL, stderr=slave, start_new_session=True,
                              preexec_fn=lambda: fcntl.ioctl(slave, termios.TIOCSCTTY, 0))  # as a shell does
    ready.started.append(worker)
    os.close(slave)
    try:
        raw, deadline = b"", time.monotonic() + 30
        while not all(t in raw.decode(errors="replace") for t in until_texts):
            assert time.monotonic() < deadline, raw.decode(errors="replace")
            if select.select([master], [], [], 1)[0]:
                raw += os.read(master, 4096)
        return raw.decode(errors="replace")
    finally:
        os.close(master)


def one_ok_one_failed(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }\n"public.missing" = { key = ["id"] }'))


def test_no_color_gives_the_same_lines_without_escape_codes(ready):
    one_ok_one_failed(ready)
    coloured, plain = (ready.run("run", "erp", env=COLOUR | e).stderr for e in ({}, {"NO_COLOR": "1"}))
    assert "\033[31m✘ raw_erp.missing" in coloured and "\033" not in plain
    same = lambda err: sorted(re.sub(r"\d", "0", re.sub(r"\033\[\d+m", "", err)).splitlines())  # times, runs
    assert same(coloured) == same(plain), plain
    assert re.search(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ✘ raw_erp\.missing +failed +\d+\.\ds  \S", plain, re.M), plain


def test_term_dumb_gives_no_escape_codes(ready):
    one_ok_one_failed(ready)
    err = ready.run("run", "erp", env=COLOUR | {"TERM": "dumb"}).stderr
    assert "raw_erp.customers" in err and "\033" not in err, err


def test_a_broken_stderr_pipe_does_not_change_the_exit_code(tmp_path):
    r, w = os.pipe()
    os.close(r)  # the reader is gone
    code = "import sys; from rowvioli import work; work.say('x'); sys.exit(0)"
    p = subprocess.run([sys.executable, "-c", code], stderr=w, capture_output=False, stdout=subprocess.PIPE, timeout=30)
    os.close(w)
    assert p.returncode == 0, p.returncode


def test_say_without_a_stderr_does_not_raise(monkeypatch):
    monkeypatch.setattr("sys.stderr", None)
    work.say("x")


def test_a_stderr_that_is_the_journal_gets_no_colour_and_any_other_does(ready, tmp_path):
    one_ok_one_failed(ready)
    for name, other in (("journal", 0), ("file", 1)):  # JOURNAL_STREAM is inherited: only stderr's own counts
        with open(tmp_path / name, "w+") as f:
            s = os.fstat(f.fileno())
            subprocess.run([ROWVIOLI, "run", "erp"], cwd=ready.dir, stdout=subprocess.DEVNULL, stderr=f, timeout=60,
                           env=ready._env(COLOUR | {"JOURNAL_STREAM": f"{s.st_dev}:{s.st_ino + other}"}))
            f.seek(0)
            err = f.read()
        assert ("\033" in err) == bool(other) and "raw_erp.customers" in err, err


def test_a_stderr_that_cannot_encode_the_marks_loses_no_line(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    r = ready.run("run", env=COLOUR | {"PYTHONIOENCODING": "ascii"})
    assert r.returncode == 0 and re.search(r"\\u2714 raw_erp\.customers +ok ", r.stderr), r.stderr


def test_work_at_a_terminal_shows_the_lines_and_a_status_line(ready):
    one_ok_one_failed(ready)
    out = at_a_terminal(ready, COLOUR | {"PYTHONIOENCODING": "utf-8"}, "✘", "✔")
    assert "/4 slots" in out and re.search(r"\033\[0m ▶ raw_erp\.customers +started +run \d+", out), out
    assert re.search(r"\r\033\[K\033\[2m\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\033\[0m \033\[32m✔ raw_erp\.customers +ok ", out), out


def test_work_at_a_terminal_with_no_color_still_shows_the_status_line(ready):
    one_ok_one_failed(ready)
    out = at_a_terminal(ready, COLOUR | {"NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}, "✘", "✔")
    assert "/4 slots" in out and "\033[3" not in out and "\033[2m" not in out, out


def test_the_status_line_lists_the_longest_running_first_and_counts_what_does_not_fit():
    runs = {i: {"claimed": f"raw_erp.t{i}", "started": 1000 - i * 10} for i in range(15)}  # t14 runs longest
    line = work.status_line(15, runs, 1000, 100)
    assert line[0] in work.SPIN and line[1:].startswith(" 15/15 slots  raw_erp.t14 ") and len(line) <= 100
    shown = line.split("slots  ")[1].split(" · ")
    *entries, more = shown
    assert more.startswith("+") and len(entries) + int(more[1:]) == 15
    assert entries[:2] == ["raw_erp.t14 140.0s", "raw_erp.t13 130.0s"]
    assert all(re.fullmatch(r"raw_erp\.t\d+ \d+\.\ds", e) for e in entries)
    wide = work.status_line(15, runs, 1000, 400)
    assert "+" not in wide and wide.count(" · ") == 14
    assert work.status_line(4, {}, 1000, 100)[1:] == " 0/4 slots  idle"
    assert work.status_line(4, {"starting": None}, 1000, 100)[1:].rstrip() == " 1/4 slots"  # nothing claimed yet
    assert len(work.status_line(4, {}, 1000, 5)) <= 5
    assert not work.status_line(4, {"starting": None}, 1000, 100).endswith(" ")
