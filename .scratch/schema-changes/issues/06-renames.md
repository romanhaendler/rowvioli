# 06: Renames: the proof and `renamed`

**Blocked by:** 04, 05

**Status:** claimed

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

- Tested in `tests/test_renames.py` (and `tests/test_apply_mistakes.py` for the setting). Not seen red, because the code another case drove already did them: the "not assumed" cases (seen red instead by weakening the proof once), A27, A28, A31, and the stated renames after the first (flag). A28 is tested as the known limit the cases describe (every row a `U`, no rename).
- Left the spec: `renamed` is stored with the table's options and taken out before the connector is called, rather than known to `known_options`, so that no connector (DuckDB's options, a connector of one's own) ever sees it. A stated rename onto a name the change log already has stops with the way out (rename that log column); on a table with a change log it acts only if the old column is in the change log, else the old column stops as one not known to be from the source; `apply` refuses an old name stated twice. For a file or REST source a stated old column is not filled empty, so `renamed` works there (cases F2). The proof needs a change log (rule 1), runs only when the key is unchanged after stated renames, compares the other columns only where both sides are of one family, and a proof must be the only one for its gone and for its new column.
