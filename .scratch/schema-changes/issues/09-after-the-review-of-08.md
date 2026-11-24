# 09: Two findings of the review of ticket 08

**Blocked by:** 08

**Status:** claimed

**Model:** Opus

Spec: `.scratch/schema-changes/spec.md`; ticket 08 and its comments.

## What to build

1. **A mirror column that the change log does not have is never written by a run** (story 8, `cases.md` G1). Today a column a person added to the mirror stops the run with "not in the change log" only while the source lacks it or brings it in another family; once the source brings the name in the same family, the person's values are overwritten without a word. It stops in that case too, with the same reason and a way out that says both choices (drop the person's column, or rename it). A table without a change log cannot tell and is unchanged.
2. **A pin taken out of a file table's `columns` is a change of type by the definition** (ticket 08, item 4): the column goes back to what the file brings (`text` for CSV and Excel, `jsonb` for JSON, the file's own type for Parquet) by the same rules as a pin that changes: go and come with a change log, the stop with its way out without one. Today it stops with the hint "pin it under columns", which is the wrong way round.
3. **A reason never shows a value of the source** (added by the owner). A first type under `columns` for a CSV column whose values do not cast fails at read with DuckDB's message, which holds the value (`Could not convert string 'secret-value' to INT32`). It stops with the table, the column, the type it does not cast to and the way out, as REST's reasons do. The same for every other place where a driver's or Postgres's message carrying a row's value reaches a reason or stderr; names of tables, columns, constraints and of a consumer's dependent object stay (spec decision 15).

## Acceptance criteria

- [ ] A test for each, seen red first, at the existing seam; the replay invariant where columns change.
- [ ] The existing tests pass or are changed to the new behaviour.

## Comments

- Item 1 also stops a column dropped from the change log by hand while the mirror keeps it (it is not told from a person's): `test_columns.py` now takes the drop as its way out. A rename is no way past the stop: the renamed column stops as any of a person's own (G1), which the test shows.
- Item 2 left the ticket for Parquet: the run keeps no memory of an earlier pin, and Parquet's own types can flip, so a pin taken out of a Parquet column of another family still stops with the hint to pin it. CSV, Excel and JSON deliver every unpinned column as `text` or `jsonb`, so there the run can tell.
- Item 3, found and not fixed: an ODBC driver's message (SQL Server's `Conversion failed when converting the varchar value '…' to data type int`; psqlODBC writes text after Postgres's message, which the end-of-line pattern then misses) can only be tried in `tests/odbc/run.sh`; a connector of one's own whose Arrow message holds a value. Checked and clean in the first line, which is all a reason takes: DuckDB's reader errors (CSV structure, bad UTF-8, malformed JSON), the target's unique, foreign key, check and not-null violations (the value is in DETAIL), the fit test's casts (22003 names no value).
