# 08: The suite runs in parallel

**Blocked by:** none

**Status:** resolved

**Model:** Sonnet

The owner agreed to `pytest-xdist` as a development dependency. The suite takes about 7.5 minutes
(`327 passed, 7 skipped in 449.87s`), one test after the other.

## What to build

- `pytest-xdist` in the development dependencies (`pyproject.toml`, `uv.lock`), nothing in the package's own.
- The harness (`tests/conftest.py`) works with several processes: each already gets a fresh database per test;
  find out whether the containers are shared or one pair per process, and take whichever is smaller on disk
  and still isolated. Containers and their volumes are removed at the end as today, also after Ctrl-C.
- Tests that measure time or kill processes (`test_crashes.py`, `test_work.py`, `max_seconds`, the pause) must
  not become flaky under load. Run the whole suite three times in parallel; a test that fails once is fixed
  at its cause or kept serial (one xdist group), never given a longer sleep or a retry.
- The number of processes is the default of plain `uv run pytest` (in `pyproject.toml`), chosen by
  measurement on this machine; `-n 0` still runs serially. CI (`.github/workflows/tests.yml`) uses what fits
  its runners (two to four cores): say what you chose and why.
- `tests/odbc/run.sh` still works.

## Acceptance criteria

- [ ] Three parallel runs in a row, same passed/skipped counts as serial, no failure.
- [ ] Wall clock before and after in the comment, with the number of processes.
- [ ] `docker ps -a` and `docker volume ls` show nothing of the suite afterwards; `df -h .` before and after.

## Comments

**Design: one shared pair of containers, not one pair per process.** The controller process starts the two
Postgres containers in `pytest_configure` and removes them in `pytest_unconfigure` (which also runs after
Ctrl-C; checked by interrupting a run: containers and their volumes were gone). The xdist workers start after
that and inherit the container names through an environment variable; the `servers` fixture only reads it.
One pair per worker would have run the session fixture once per process, with four workers four times the
containers, volumes and start-up, and a worker killed hard would leave its pair behind. Isolation is unchanged:
each test still creates its own database in each container. The server is started with `max_connections=500`
(default 100): with four tests in parallel, each holding connections of its own plus its worker and run
processes, 100 is close enough to be a source of failures that look like flakiness. `-n 0` still works (the
controller is then the only process); `--collect-only` starts no containers.

**Timings** (8 cores, machine shared with other agents running their own suites, so all numbers are under load):

- serial (`-n 0`): `327 passed, 7 skipped in 487.95s (0:08:07)`
- `-n 4`, four runs in a row: 168.62s, 147.56s, 145.09s, 131.71s; each `327 passed, 7 skipped`
- `-n 8`, one run: 111.97s, `327 passed, 7 skipped`

**Default `-n 4`** (`addopts` in `pyproject.toml`): roughly 3.3x faster than serial; `-n 8` is only another
1.3x and uses every core of a machine that is shared here, which is where the time-based tests would suffer
first. No test failed in any of the five parallel runs, so none had to be fixed or grouped; no sleep, retry or
assertion was touched.

**CI** keeps the default of four: GitHub's `ubuntu-24.04` runners for public repositories have four cores.
On a two-core runner pass `-n 2`.

`tests/odbc/run.sh` still works (7 passed, 1 skipped in its container with four workers). After every run
`docker ps -a` showed no `rowvioli-test` container left. Free disk: 85 GB before, 91 GB after.
