# 05: Keys and the history view by stretches

**Blocked by:** 03

**Status:** ready-for-agent

**Model:** Opus

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 4 of the spec: implementation decisions 7 to 9. Stories 17 to 24.

The key compared as a set; a first key; another key (`D` and `I` at the moment of the run); a key taken away; a primary key changed by hand put back; a widened key column (with ticket 04 if it is merged, otherwise a sentence here); the stops of story 22. The history view with one branch per key, built from the comment on `_op` and from nothing in `_rowvioli`. Recorded in the columns table (`key`).

The part "after renames" of decision 7 is ticket 06.

## Acceptance criteria

- [ ] Spec "What is tested" 4: `cases.md` C1 to C15 except C11, each as a test named after its number or a sentence here why not; the history at moments before and after the change, with a row whose new key column changed under the old key; the three objects renamed by hand after a change of key; the comment removed.
- [ ] The replay invariant (from the last change of key) in every test that changes the key.
- [ ] A foreign key of a consumer stops the change and is named (story 23).
- [ ] The existing tests pass or are changed to the new behaviour. No documents (ticket 07).

## Comments
