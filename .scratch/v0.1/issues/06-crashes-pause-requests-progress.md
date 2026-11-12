# 06: Crashes, pause, requests, progress

**Blocked by:** 03

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** A run killed at any step leaves the mirror unchanged and releases its lock; a dead run shows as `failed` with `worker lost` and is tried again after the pause (1, 2, 4, 8 minutes, never beyond one maximum age). Requests through `requested_at` behave as README "Loading now" says: several before a run cause one run, one during a run causes one more, one during a run that fails causes one more at once. A concurrent reader never sees an empty or half-loaded mirror. While a table is loading, the status view shows the rows written so far (from `pg_stat_progress_copy` of the lock holder's backend) and the rows of the last successful run, and nothing when that is not visible (decision 31).

- [x] The prototype's `test_crashes` and `test_pause_requests` suites pass
- [x] While a run is held filling, the status view shows rows written so far greater than zero (spec test 18)

## Comments

- Most of the behaviour already held after 03/05/07. Unskipping the prototype suites showed one gap: a run whose target backend is terminated crashed in `fail()`, and `run` reported `worker lost`. It now answers `connection to the target lost` (a fixed text, so it cannot leak a secret), as in the prototype.
- Progress columns in `_rowvioli.status`: `rows_written` (`tuples_processed` of the lock holder's `pg_stat_progress_copy` row) and `rows_last_run` (`rows_read` of the last `ok` run). Both are null unless the table is loading. `rows_written` is also null after filling (no COPY running) and when the role cannot see it. The view changed inside schema version 1 (0.1 is unreleased). README "Target schema" and the UI table are updated.
- Test: `test_while_filling_the_status_shows_the_rows_written_so_far_and_those_of_the_last_run` in `tests/test_crashes.py`.
