# 01: The rule: schema version 2, two columns, one more term in the view

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

Spec: `.scratch/load-times/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program.

## What to build

Spec sections "The rule" and "Schema". Only `src/rowvioli/sql/schema.sql` and tests change.

- `_rowvioli.tables` gets two definition columns next to the other settings: `at time[]` and `timezone text`, both may be empty.
- `_rowvioli.status`: `due_at` is the earlier of today's formula and the next load time, the earliest point in time later than `attempted_at` that falls on one of `at` in `timezone`. Never attempted stays "now". The view's columns do not change. The conversion of a local time is Postgres' own (`AT TIME ZONE`), no code for summer time.
- Schema version 2, edited in place, no migration.

## Acceptance criteria

- [ ] Spec "What is tested" 1 to 11, in `tests/test_status.py`, with facts written by SQL and fixed dates.
- [ ] The existing status tests pass unchanged.
- [ ] Spec test 16: `tests/test_init.py` expects version 2. (The refusal test itself uses 99 and needs no change.)
- [ ] A row with a non-empty `at` and no `timezone` does not break the view (it has no next load time).

## Comments
