# 08: The suite runs in parallel

**Blocked by:** none

**Status:** ready-for-agent

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
