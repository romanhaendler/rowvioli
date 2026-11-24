"""`rowvioli work`, the order of loading, both limits, `max_seconds`, SIGTERM and an unreachable target
(spec tests 9, 10, 11, 13, 14, 19)."""
import contextlib
import io
import os
import pty
import re
import select
import signal
import socket
import subprocess
import sys
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


@pytest.mark.parametrize("command", ["work", "run"])
def test_ctrl_c_ends_the_worker_with_one_line_130_and_no_run_process_left(ready, command):
    slow(ready, "hanging", 60, 1)
    apply(ready, source(ready, "erp", "", '"public.hanging" = { key = ["id"] }'))
    worker = subprocess.Popen([ROWVIOLI, command], cwd=ready.dir, env=ready._env(None), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, start_new_session=True)
    ready.started.append(worker)
    until(lambda: ready.target("select status from _rowvioli.status") == [("loading",)])
    [run] = [int(x) for x in subprocess.run(["pgrep", "-P", str(worker.pid)], capture_output=True, text=True).stdout.split()]
    time.sleep(1)  # the run is inside its source read, where the driver's own SIGINT handler would cancel it
    os.killpg(worker.pid, signal.SIGINT)  # as a terminal does: to the whole foreground process group
    assert worker.wait(timeout=10) == 130
    err = worker.stderr.read()
    assert re.search(r"stopped by Ctrl\+C, 1 run ended$", err.strip()) and "Traceback" not in err, err
    assert not alive(run)
    assert worker.stdout.read() == ""  # `run` writes no answer
    until(lambda: ready.target("select status from _rowvioli.status") == [("failed",)], timeout=20)  # as after SIGKILL
    assert ready.target("select reason from _rowvioli.status") == [("worker lost",)]
    assert ready.target("select status, reason from _rowvioli.runs") == [("running", None)]  # nothing recorded


def test_with_the_limits_full_the_targets_connections_stay_at_the_running_tables_plus_one_per_worker(ready):
    tables = "\n".join(f'"public.slow{i}" = {{ key = ["id"] }}' for i in range(4))
    for i in range(4):
        slow(ready, f"slow{i}", 3600, 1)  # loading for longer than the test looks, however busy the machine
    apply(ready, source(ready, "erp", "parallel = 4", tables))
    ready.target("update _rowvioli.meta set max_running = 2")
    workers = [ready.start("work", "--slots", "4") for _ in range(3)]
    connections = """select count(*) from pg_stat_activity
                      where datname = current_database() and pid <> pg_backend_pid()"""

    def runs():  # the run processes of all three workers
        return sum(len(subprocess.run(["pgrep", "-P", str(w.pid)], capture_output=True, text=True).stdout.split())
                   for w in workers)
    # one connection for all the counting: ready.target opens one per query, and on a busy machine the backend of
    # the query before is still closing when the next one counts, which reads as a sixth connection
    with psycopg.connect(ready.target_url, autocommit=True) as counting:
        def count():
            return counting.execute(connections).fetchone()[0]
        # the start-up is over when two tables load, their two run processes alone are left (one started before the
        # first claims committed finds nothing and ends) and every worker has connected
        until(lambda: ready.target("select count(*) from _rowvioli.status where status = 'loading'") == [(2,)]
              and runs() == 2 and count() == 2 + 3, timeout=60)
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
        assert err.count("⚠ the target is unreachable") == 1, err  # once per outage
        assert len(re.findall(r"✔ the target is reachable again after \d+s", err)) == 1, err
        assert err.index("⚠ the target is unreachable") < err.index("reachable again"), err
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


def test_work_shows_the_mascot_before_its_start_line_at_a_terminal_and_nothing_that_moves_the_cursor(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    master, slave = pty.openpty()
    worker = subprocess.Popen([ROWVIOLI, "work"], cwd=ready.dir, env=ready._env(COLOUR | {"PYTHONIOENCODING": "utf-8"}),
                              stdout=subprocess.DEVNULL, stderr=slave)
    ready.started.append(worker)
    os.close(slave)
    try:
        raw = b""
        while "✔" not in raw.decode(errors="replace"):
            assert select.select([master], [], [], 10)[0], raw
            raw += os.read(master, 4096)
        out = raw.decode()
        assert "{   v   }-[#]-{   v   }" in out.split("started with")[0]
        assert "\033[K" not in out and "\r" not in out.replace("\r\n", "") and not set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏") & set(out), out
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


def test_a_message_the_program_stops_with_keeps_exit_code_1_on_a_broken_stderr_pipe(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "ROWVIOLI_TARGET_URL"}
    r, w = os.pipe()
    os.close(r)  # the reader is gone
    p = subprocess.run([ROWVIOLI, "status"], cwd=tmp_path, env=env, stderr=w, stdout=subprocess.PIPE, timeout=30)
    os.close(w)
    assert p.returncode == 1, p.returncode
    p = subprocess.run([ROWVIOLI, "status"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert (p.returncode, p.stderr) == (1, "ROWVIOLI_TARGET_URL is not set\n")


def test_a_write_that_fails_once_loses_only_its_own_line():
    r, w = os.pipe()
    os.set_blocking(w, False)  # the file description is shared, so the worker's stderr is non-blocking too
    with contextlib.suppress(BlockingIOError):
        while True:
            os.write(w, b"." * 4096)  # full: the first line fails
    code = ("import sys; from rowvioli import work; work.say('lost'); print('tried', flush=True); "
            "sys.stdin.readline(); work.say('written'); sys.exit(0)")
    p = subprocess.Popen([sys.executable, "-c", code], stderr=w, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True)
    os.close(w)
    assert p.stdout.readline() == "tried\n"
    os.set_blocking(r, False)  # the failure passes: the pipe is drained
    with contextlib.suppress(BlockingIOError):
        while os.read(r, 65536):
            pass
    p.communicate("\n", timeout=30)
    os.set_blocking(r, True)
    with os.fdopen(r, "rb") as f:
        err = f.read()
    assert p.returncode == 0 and b"written" in err, err


def test_say_without_a_stderr_does_not_raise(monkeypatch):
    monkeypatch.setattr("sys.stderr", None)
    work.say("x")


def test_say_to_a_stderr_without_an_encoding_does_not_raise():
    with contextlib.redirect_stderr(io.StringIO()):
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


def test_control_characters_in_a_table_name_never_reach_the_log(ready):
    ready.source("create table customers (id int primary key)")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }'))
    # `apply` refuses such a name now; one applied by an older version is in the target and keeps loading
    ready.target("update _rowvioli.tables set target_table = %s", ["a\033[2J\nBBB\r\033]0;T\a"])
    r = ready.run("run", "erp", env=COLOUR | {"NO_COLOR": "1"})
    assert "\033" not in r.stderr and "\r" not in r.stderr and "\a" not in r.stderr, repr(r.stderr)
    assert len(r.stderr.splitlines()) == 2, r.stderr  # started and ok, no forged line
    assert "a?[2J?BBB??]0;T?" in r.stderr


def test_say_writes_a_reason_with_control_characters_as_question_marks(capsys):
    work.say("failed: bad \033[31mvalue\r\n\x9bforged")
    err = capsys.readouterr().err
    assert err.endswith(" failed: bad ?[31mvalue???forged\n") and err.count("\n") == 1 and "\033" not in err
    work.say("one\u2028two\u2029three")  # str.splitlines() splits there
    assert capsys.readouterr().err.endswith(" one?two?three\n")


def test_plain_replaces_exactly_the_c0_del_and_c1_characters_and_the_two_line_separators():
    for code in (0x00, 0x1f, 0x7f, 0x9f, 0x2028, 0x2029):
        assert work.plain(chr(code)) == "?", hex(code)
    for code in (0x20, 0x7e, 0xa0):
        assert work.plain(chr(code)) == chr(code), hex(code)


def test_the_marks_are_green_red_and_yellow(monkeypatch, capsys):
    monkeypatch.setattr(work, "colour", lambda: True)
    for mark, code in (("✔", 32), ("✘", 31), ("⚠", 33)):
        work.say("x", mark)
        assert capsys.readouterr().err.endswith(f" \033[{code}m{mark} x\033[0m\n")


def test_the_target_table_of_a_run_line_is_padded_to_28_characters(monkeypatch, capsys):
    monkeypatch.setattr(work, "colour", lambda: False)
    work.say_run({"claimed": "raw_erp.t", "started": time.monotonic()}, "started", "run 1")
    assert f"▶ {'raw_erp.t':<28} started " in capsys.readouterr().err


def test_two_workers_and_a_run_on_a_table_whose_shape_changes_publish_each_change_once(ready):  # ticket 14, item 4
    from test_columns import replays
    from test_columns_go_and_come import columns, log_replays
    ready.source("create table customers (id int primary key, v int, city text);"
                 "insert into customers select g, g, 'c' || g from generate_series(1, 30) g")
    apply(ready, source(ready, "erp", "", '"public.customers" = { key = ["id"] }').replace('"1h"', '"1s"'))
    workers = [ready.start("work", "--slots", "2") for _ in range(2)]
    shape = "select format_type(atttypid, atttypmod) from pg_attribute where attrelid = 'raw_erp.customers'::regclass" \
            " and attname = 'v'"
    until(lambda: ready.target("select status from _rowvioli.status") == [("ok",)], timeout=30)
    for change, published in [
            ("alter table customers drop column city", lambda: columns(ready) == ["id", "v"]),
            ("alter table customers add column city text; update customers set city = 'x' || id",
             lambda: "city" in columns(ready) and ready.target("select count(city) from raw_erp.customers") == [(30,)]),
            ("alter table customers alter v type bigint; update customers set v = 10000000000 where id = 1",
             lambda: ready.target(shape) == [("bigint",)]),
            ("alter table customers alter v type text using v || 'x'", lambda: ready.target(shape) == [("text",)])]:
        ready.source(change)
        racing = [ready.start("run", "erp") for _ in range(2)]  # beside the workers, on the same table
        until(published, timeout=30)
        for r in racing:
            assert r.wait(timeout=30) in (0, 1)
    for w in workers:
        w.send_signal(signal.SIGTERM)
        assert w.wait(timeout=30) == 0
    assert ready.target("select reason from _rowvioli.runs where status <> 'ok'") == []
    # each change once in the columns table, in its order
    assert [(c, op, type, mirror) for c, op, type, mirror in ready.target(
        'select "column", _op, type, mirror from _rowvioli.columns__log where "column" in (\'city\', \'v\') '
        'order by _loaded_at, "column"')] == [
        ("city", "I", "text", True), ("v", "I", "integer", True), ("city", "U", "text", False),
        ("city", "U", "text", True), ("v", "U", "bigint", True), ("v", "U", "text", True)]
    replays(ready)
    log_replays(ready)
