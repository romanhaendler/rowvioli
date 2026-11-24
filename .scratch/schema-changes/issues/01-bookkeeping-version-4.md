# 01: Version 4 of the bookkeeping, versions in runs, the untried cases

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 0 of the spec.

- Tests of the program **as it behaves today** for `cases.md` A20, A22, B14, B16, F8. They pin today's behaviour; no change of the program for them.
- Implementation decision 24: version 4 of `_rowvioli`, the migration in `rowvioli init` written as a list of steps. In this ticket the migration adds only the two version columns of `runs`; ticket 02 adds the columns table to the same step (version 4 is not released in between).
- Implementation decision 11, first half: `runs` records the version of the program and of the driver; the optional driver version in the connector contract; the test connector in `tests/connector` reports a version given to it. The `by = reader` record itself is ticket 02.

## Acceptance criteria

- [ ] Spec "What is tested" 0, in the files named there as prior art.
- [ ] `init` on a version 3 target brings it to 4 and changes nothing else; an old worker refuses version 4 (story 46).
- [ ] The existing tests pass. No documents in this ticket (ticket 07).

## Comments
