# 02: The columns table

**Blocked by:** 01

**Status:** claimed

**Model:** Sonnet

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 1 of the spec: implementation decisions 16 to 23, and the second half of 11 (`by = reader`). Stories 31 to 35, 37 to 39, 42.

`_rowvioli.columns`, `columns__log`, `columns__history`, added to the version 4 step of the migration from ticket 01. Written in the publishing transaction only, for every table. First fill (`found`), a new column (`source`), changes by hand, a mirror renamed by hand, `pg_notify` on `rowvioli_schema`, the rights. **No change of what a run does to a target table**, except decision 20's last sentence (a type widened by hand in the mirror is followed in the change log).

Write the recording so that tickets 03 to 06 can hand it the changes of their plan (rows per decision 19, note per decision 22) without reshaping it.

## Acceptance criteria

- [ ] Spec "What is tested" 1 (`tests/test_history.py` as prior art); the notification with a second connection that listens, for a run that commits and one that fails.
- [ ] `_loaded_at` in `columns__log` equals that of the rows published in the same transaction (story 33).
- [ ] The existing tests pass. No documents in this ticket (ticket 07).

## Comments

- Not tested: a column a person added to the mirror (not the change log): the run fails before publishing with `is missing in the source`, so nothing is recorded (decision 3 changes that in ticket 03). Not tested: a type widened by hand in the mirror other than `numeric(p,s)`: the run still stops at `has changed its type` until ticket 04's families; only numeric is followed in the change log.
- Left the spec: the notification is not sent for a first fill (every row `found`), only when something else was recorded (a new column, a change by hand, a renamed mirror); a table's first fill is no change of columns.
