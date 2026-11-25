# 07: Documents and the new decision

**Blocked by:** 06

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 6 of the spec: implementation decisions 25 to 27, story 48, and the known limits from "Further Notes" into `docs/open-points.md`. Describe what the program on this branch does; where it differs from the spec, say so in a comment here instead of documenting the spec.

Also `CHANGELOG` in the manner of its existing entries.

## Acceptance criteria

- [ ] Glossary, the new decision with the "Changed by decision …" notes on 17, 31, 40, 49, `docs/loading.md`, `target.md`, `definition.md`, `connector-guide.md`, `operation.md`, `open-points.md`.
- [ ] `tests/test_guide.py` and the like keep the examples true (spec "What is tested" 6).
- [ ] No change of the program.

## Comments

- Written from the program on `schema-changes` (d3dc412) in `GLOSSARY.md`, decision 54 in `docs/decisions.md` (with the notes on 17, 31, 40, 49), `docs/loading.md`, `target.md`, `definition.md`, `connector-guide.md`, `connectors.md`, `operation.md`, `commands.md`, `open-points.md`, `README.md` (one sentence) and `CHANGELOG.md`. The changelog entry is headed `Unreleased`, since no version is set. `connectors.md` and `commands.md` were not in the ticket's list; they said what no longer holds (file patterns with other columns, REST columns absent from a page, the program never alters a column, what `init` does).
- Where the program differs from the spec and the documents describe the program:
  - Decision 3, for a file or REST table without a change log (ticket 08, 1): a missing mirror column stops with the old reason and its way out.
  - Decision 6, for a type under `columns` (ticket 08, 4): goes and comes by the definition, `by = definition`; also a column taken out of a REST table's `columns`; a type a Parquet file brings itself still stops with the hint. `by = definition` is given to every column named under `columns`, also one that comes.
  - Decision 23 (ticket 08, 2): `init` prints the grants. Decision 11 (ticket 08, 3): every shipped connector reports `driver_version`, empty without package metadata. Ticket 08, 5: a type changed by hand to another family stops and the reason names the drop.
  - The notification (decision 16) is not sent for a first fill (ticket 02).
  - A column gone, or a type of another family, in a table without a change log stops with today's reason plus the way out (story 47); a key column of another family names `target_table` as the way out (tickets 03, 04). A retired log column is recognised by its name, not by the columns table (ticket 03). A change log narrowed by hand is widened to the type that holds its own values and the source's, which can be wider than the mirror's (ticket 04).
  - Decision 7, a primary key that differs: put back (`hand`) or another key (`definition`) is told by the key the columns table recorded; without rows there it counts as another key (ticket 05). The text to put back the comment on `_op` is the latest note `the change log's keys: ...` in `columns__log`; every change log the program begins has the comment with its one key.
  - Decision 10, `renamed`: stored with the table's options and taken out before the connector is called, not in `known_options`; on a table with a change log it acts only if the old column is in the change log, else the old column stops as not known to be from the source; it stops onto a name the change log has; `apply` refuses an old name stated twice; it works for a file or REST source (ticket 06). The proof also needs the key unchanged after stated renames and its columns in one family, compares only columns of one family on both sides, and each proof must be the only one for its gone and its new column.
- Ticket 09 (two behaviours on another branch) is documented as the ticket states it, not as the code of `schema-changes` does: a mirror column the change log does not have stops the run also when the source brings the name in the same family (`loading.md` "The stops", `CHANGELOG.md`), and a pin taken out of a file table's `columns` is a change of type by the definition (`definition.md`). The reason's exact words after `is not in the change log, so it is not known to be from the source` are not quoted; today's way out in the code names the drop and adding to the change log, and the ticket says drop or rename. Check both against the merged ticket 09.
- Resolved on branch `schema-changes`, from sc-07 (87d0075). Review fixes: 7fcd4d2, 3843fdb, 87d0075.
