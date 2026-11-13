# 02: History: a complete change log that says when, and its view

**Blocked by:** 01

**Status:** ready-for-agent

**Model:** Opus

Spec: `.scratch/target-names-and-history/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program. Disk: check `df -h .` and `docker system df` before and after; remove the containers and volumes your tests created.

## What to build

Spec stories 17 to 34 and the implementation decisions under "History".

- `_loaded_at` in every change log row, written with the publishing transaction's `now()`, equal to `tables.loaded_at`.
- The three cases of a complete log: created (every row of the mirror as `I`), appended, or the run fails in the checks before publishing with a reason that names the log.
- The view `<target table>__history`: created when missing, replaced when a column was added to the log, otherwise untouched and unlocked.
- `_loaded_at`, `_valid_from`, `_valid_to` reserved next to `_op` and `_run`.

Not in this ticket: an index, the measurement (03), documents (04).

## Acceptance criteria

- [ ] Tests 10 to 20 of the spec's "What is tested" exist and pass, and the history-view half of test 6.
- [ ] Tests read the view and the mirror with SQL, never the view's definition text; no simulated clock.
- [ ] The whole suite passes.
