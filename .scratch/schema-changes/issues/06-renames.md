# 06: Renames: the proof and `renamed`

**Blocked by:** 04, 05

**Status:** ready-for-agent

**Model:** Opus

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 5 of the spec: implementation decision 10, the comment rewritten on a rename (9), the key compared after renames (7). Stories 25 to 29.

The proof as one query, its numbers as constants in one place; the table setting `renamed = { new = "old" }` (also in `known_options` and whatever `apply` checks); no row written; the columns table gets `D` and `I` with `was` and the three numbers in the note.

## Acceptance criteria

- [ ] Spec "What is tested" 5: `cases.md` A24 to A28, A31, each as a test named after its number or a sentence here why not; a flag, a small table, two candidates are not proven; `renamed` for a key column, on a table without a log, left in place while the old column exists; different families fail.
- [ ] A consumer's view on a renamed column keeps working under its own column name (story 26).
- [ ] The replay invariant in every test.
- [ ] The existing tests pass. No documents except what a test of the documents forces (ticket 07).

## Comments
