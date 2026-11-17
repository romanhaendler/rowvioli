# 03: Files: JSON, a pattern, the CSV leads

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Opus

Spec: `.scratch/out-of-the-box/spec.md` (read it first, also "Testing Decisions"). Behaviour reference: `README.md`, `docs/decisions.md`. Tests: `tests/conftest.py`, `rv` fixture. Documents are ticket 04: change no `.md` outside your ticket file, but list under `## Comments` every sentence the documents need.

## What to build

In `src/rowvioli/connectors/file.py` (and `definition.py` for the one `apply` check):

- **JSON**: `.json`, `.jsonl`, `.ndjson` through DuckDB's reader. Find out and measure what arrives in the
  target for numbers, dates, nulls, nested objects and arrays, and for a second run (the diff needs equality).
  A value that cannot arrive right fails the run and names the column. `tables` lists these files too.
- **A pattern**: a table name with `*` or `?` reads every matching file as one table. The connector expands
  it inside the connection's `path`, resolves every match and refuses any outside (symlink, `..`, absolute);
  no match fails. Files of different extensions or columns fail with a reason a person can act on. `apply`
  fails for a pattern without `target_table` and says so.
- **Leads from the second shakedown**, reproduce first: a CSV with an unterminated quote loads two rows
  without an error (a silent wrong); a ragged CSV names the wrong cause (`has no column id; it has: id,name`).
  Fix what goes red and can be fixed in the connector; record the rest in the comment as a known limit.

## Acceptance criteria

- [ ] A JSON and a JSON-lines file mirror, and a second unchanged run reports no change.
- [ ] `orders_*.csv` over two files mirrors both; a third file arrives on the next run.
- [ ] A pattern cannot read outside `path`: the existing confinement tests have a pattern twin.
- [ ] The whole suite is green.

## Comments
