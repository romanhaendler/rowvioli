# 01: A worker says what it does

**Blocked by:** None (can start immediately)

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/visibility/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program.

## What to build

Spec stories 1 to 21 and the implementation decisions about the lines. The loop in `src/rowvioli/work.py` writes one line per event on stderr; the run processes (`load.py`) do not change and their stderr stays discarded.

- One small function writes a line: local date and time to the second, a space, the text. The existing "target is unreachable" line goes through it and stays once per outage.
- Start line of `work` only (not `run`): worker name, slots, `current_database()`. Never a part of `ROWVIOLI_TARGET_URL`.
- Start line on a claim, `ok` or `failed` line on the answer, duration measured by the loop, one decimal. `max_seconds` and `worker lost` use the same failure line. A run process that ended before a claim gives a line with its exit code.
- Waiting line (`work` only): once per change from busy to waiting, again only after a run of this worker ended or the target was unreachable in between. One query on the existing connection for the enabled, not loading table with the earliest `due_at`; `due since HH:MM:SS` when it is in the past; `nothing due` alone when there is no such table.
- Stopping line on SIGTERM with the number of runs that finish.
- No setting, no `logging` module, no levels.

## Acceptance criteria

- [ ] Spec "What is tested" 1 to 8, in the test files named there as prior art (`tests/test_work.py`, `tests/test_crashes.py`, `tests/test_secrets.py`, `tests/test_run.py`). Tests match the meaningful parts of a line, not the timestamp.
- [ ] The existing tests pass unchanged; stdout and exit codes of `run` are untouched.
- [ ] No documents in this ticket (ticket 03).

## Comments

Resolved on branch `visibility`, from vis-01 (5f0761a). Review fixes: 2373115.

On 2026-11-12 the owner dropped the waiting line (stories 9 to 11, its implementation decision, spec test 5) after seeing it repeat with two workers; `rowvioli status` shows what is due when. See the last bullet under "Further Notes" in `spec.md`.
