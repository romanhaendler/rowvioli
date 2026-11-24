# 03: The plan; a column goes and comes back

**Blocked by:** 02

**Status:** claimed

**Model:** Opus

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 2 of the spec: implementation decisions 1 to 3, 12 to 15, and the parts of 19 and 22 for a column that goes or is retired. Stories 1 to 10, 30, 40, 43 to 45, 47.

The plan before the diff, the diff by the plan, publishing in the order of decision 14 (lock with `NOWAIT`, retried). A column goes; comes back in the same family; comes back in another family (`<name>__<run>`). Families enter here only as far as that needs; the fixed list is decision 4 and ticket 04 builds on it. A column missing from a file or REST source is empty and never goes. Without a change log: today's stops. Everything the plan does is recorded in the columns table.

Leave the plan open for what tickets 04 to 06 add (types to widen, the key, renames) without building it.

## Acceptance criteria

- [ ] Spec "What is tested" 2: `cases.md` A5 to A16, A19, A23, F1, F6, each as a test named after its number or a sentence here why not.
- [ ] One helper in the tests replays a change log to its mirror; asserted in every test that changes columns.
- [ ] Untouched rows of the mirror are shown not rewritten when a column goes (story 5).
- [ ] A table stuck today on `is missing in the source` resolves with the first run (story 45).
- [ ] Tests of today's behaviour that this ticket changes (also those of ticket 01) are changed to the new behaviour, not deleted. No documents (ticket 07).

## Comments

- Tested only in part: A12 with values that fit the change log's type; one that does not fit fails with Postgres's own message until ticket 04 widens. A15 shares its test with A11 (same mechanics; the gap in `columns__history` is asserted). Story 10's "name that is taken" is built beside "too long" but not tested: it needs a source column named `<name>__<run>` for the very run that retires `<name>`.
- Left the spec: a column gone from a table without a change log stops with today's reason plus the way out (story 47), `...; without a change log its values are nowhere else, so a person drops it: ALTER TABLE ... DROP COLUMN ...`. A retired log column is recognised by its name (`<name>__<digits>` beside a log column `<name>`), not by the columns table, so that the plan does not need the record.
- The documents now differ from what a run does (`docs/loading.md` on dropped columns, `docs/connectors.md` and `docs/open-points.md` on file patterns with other columns and REST columns absent from an answer): ticket 07.
