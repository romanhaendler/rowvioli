# 05: Keys and the history view by stretches

**Blocked by:** 03

**Status:** resolved

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

- Not tested here: C7 (a widened key column) is ticket 04's, which was not merged into `schema-changes` when this was built; today a key column of another type stops (C8's test holds either way). C2 is `tests/test_history.py::test_C2_...`; C10 is the "occurs twice" and "is null" cases of `tests/test_checks.py` and `test_another_key_that_does_not_identify_a_row_...`; that the reason names the source's primary key is not built, since no decision of the spec asks for it. C11 is left out by the ticket.
- Left the spec: whether a primary key that differs is put back (by hand) or is another key (by the definition) is told by the key `_rowvioli.columns` recorded for the table; without rows there (the first run after the upgrade) it counts as another key. The text to put back a lost comment on `_op` is the latest note `the change log's keys: <comment>` in `columns__log`, which a change of key, and a retirement of an old key's column, write. The comment is JSON: `[{"key": ["id"]}, {"key": ["id", "tenant"], "from": "<the run's now(), ISO 8601>"}]`; every change log the program begins gets it with its one key, so one without it is from before the upgrade (one key) or lost it by hand.
- Review: the departure stays; the record decides only where the comment cannot (a change log from before the upgrade, a table without one), and `_rowvioli.runs.definition` hashes the whole definition, so it cannot tell which table's key changed. What goes wrong on the first run after the upgrade: a mirror whose primary key a person changed by hand while the definition stayed (such a table failed every run before the upgrade) counts as another key. Nothing is lost: the mirror is the source's, the change log keeps every row and gets a `D` and an `I` per row, and replays from that run. Wrong are `by = definition` in the columns table and the history before that run, read by the hand's key; the way out is to put the definition's key as the first one in the comment on `_op` and drop the history view, which the next run creates again.
- Resolved on branch `schema-changes`, from sc-05 (1580eed). Review fixes: b68443c.
