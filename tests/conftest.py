"""Test harness: two throwaway Postgres containers, the program as a real process.

Tests never import the program. They use the `rv` fixture:
  rv.run(*args, env={...})   runs `rowvioli` in rv.dir with ROWVIOLI_TARGET_URL and
                             ROWVIOLI_KEY_FILE (rv.dir/worker.key, from `key new`) set
  rv.target(sql, params)     queries the target, returns rows (or None)
  rv.source(sql, params)     the same for the source
  rv.definition({"erp.toml": "..."})  writes rv.dir/sources/, returns its path
  rv.start(*args)            like rv.run, in the background: a Popen (stdout/stderr piped), killed at test end
  rv.kill_runs(p)            kill -9 the run processes started by the worker process p
  until(check)               polls check() until it is truthy (10 s), returns its value
Each test gets a fresh database in each container, so tests and worktrees do not collide.
"""
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
import pytest

IMAGE = "postgres:16-alpine"
ROWVIOLI = shutil.which("rowvioli", path=os.path.dirname(sys.executable))


def _start(name):
    subprocess.run(["docker", "run", "-d", "--name", name, "--label", "rowvioli-test",
                    "-e", "POSTGRES_PASSWORD=x", "-p", "127.0.0.1::5432", IMAGE],
                   check=True, capture_output=True)


def _url(name, db="postgres"):
    port = subprocess.run(["docker", "port", name, "5432/tcp"], check=True, capture_output=True,
                          text=True).stdout.split()[0].rsplit(":", 1)[1]
    return f"postgresql://postgres:x@127.0.0.1:{port}/{db}"


def _wait(url):
    # during initdb the server listens on the socket only, so a TCP connect means it is ready
    for _ in range(120):
        try:
            psycopg.connect(url, connect_timeout=1).close()
            return
        except psycopg.OperationalError:
            time.sleep(0.5)
    raise RuntimeError(f"postgres at {url} did not start")


@pytest.fixture(scope="session")
def servers():
    tag = uuid.uuid4().hex[:8]
    names = {"source": f"rowvioli-test-{tag}-source", "target": f"rowvioli-test-{tag}-target"}
    try:
        for n in names.values():
            _start(n)
        for n in names.values():
            _wait(_url(n))
        yield names
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", *names.values()], capture_output=True)


def _query(url, sql, params=None):
    with psycopg.connect(url, autocommit=True) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else None


class Rv:
    def __init__(self, target_url, source_url, dir):
        self.target_url, self.source_url, self.dir = target_url, source_url, dir

        self.started = []

    def _env(self, env):
        return {**os.environ, "ROWVIOLI_TARGET_URL": self.target_url,
                "ROWVIOLI_KEY_FILE": str(self.dir / "worker.key"), **(env or {})}

    def run(self, *args, env=None, timeout=60):
        return subprocess.run([ROWVIOLI, *args], cwd=self.dir, env=self._env(env), capture_output=True,
                              text=True, timeout=timeout)

    def start(self, *args, env=None):
        p = subprocess.Popen([ROWVIOLI, *args], cwd=self.dir, env=self._env(env), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        self.started.append(p)
        return p

    def kill_runs(self, worker):
        """kill -9 every run process (child) of the worker process; returns their pids."""
        pids = [int(x) for x in subprocess.run(["pgrep", "-P", str(worker.pid)], capture_output=True,
                                               text=True).stdout.split()]
        for pid in pids:
            os.kill(pid, signal.SIGKILL)
        return pids

    def target(self, sql, params=None):
        return _query(self.target_url, sql, params)

    def source(self, sql, params=None):
        return _query(self.source_url, sql, params)

    def definition(self, files):
        d = self.dir / "sources"
        d.mkdir(exist_ok=True)
        for name, text in files.items():
            (d / name).write_text(text)
        return d


@pytest.fixture
def rv(servers, tmp_path):
    db = "t_" + uuid.uuid4().hex[:12]
    urls = {}
    for role, name in servers.items():
        _query(_url(name), f"CREATE DATABASE {db}")
        urls[role] = _url(name, db)
    rv = Rv(urls["target"], urls["source"], tmp_path)
    yield rv
    for p in rv.started:
        rv.kill_runs(p)
        p.kill()
        p.wait()


def until(check, timeout=10):
    end = time.monotonic() + timeout
    while not (value := check()):
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {check}")
        time.sleep(0.05)
    return value
