# 04: Types: fit, widen, another family

**Blocked by:** 03

**Status:** claimed

**Model:** Opus

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 3 of the spec: implementation decisions 4 to 6, and the widening step in the reason after `max_seconds` (15). Stories 11 to 16, 45.

One fit test for all families; widening mirror and change log to the type that holds both; a narrowed source changes nothing; another family is a column that goes and comes (ticket 03's mechanics), and stops for a connector without a catalog and for a key column. Replaces the handling of `numeric` alone (decision 49). Recorded in the columns table with `type` and `source_type`.

## Acceptance criteria

- [ ] Spec "What is tested" 3: `cases.md` B1 to B8, B11, B13, B19, F4, F5, each as a test named after its number or a sentence here why not; a view on the mirror while values fit, and when one does not (`tests/test_numeric.py`).
- [ ] The replay invariant in every test that changes columns.
- [ ] A table stuck today on `has changed its type` resolves with the first run (story 45).
- [ ] The existing tests pass or are changed to the new behaviour. No documents (ticket 07).

## Comments
