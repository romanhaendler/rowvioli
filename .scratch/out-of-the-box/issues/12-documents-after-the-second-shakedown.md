# 12: What the second wave looked for in the documents and did not find

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

From the shakedown of 2026-11-18 (P16 migrating team, P20 consumer, P3 staff engineer, P23 successor). Text
and one test helper; no behaviour changes.

## What to build

In `README.md` (each thing once, where a reader looks for it; try every query and command you write):

- **Taking over existing target tables** (P16): a short passage where the target schema is described. The
  tables `<name>__log` and `<name>__history` appear beside every mirror with a key, also in a schema other
  things read, and `log = false` leaves them out. Do not write about `numeric(p,s)` here: that is being decided.
- **A table that loads only at night** (P16): `at` with a `timezone` and a long `max_age`, because `max_age`
  of the source applies as well; one example.
- **A table that needs a `WHERE` or other column names** (P16, P3): a view in the source, listed as a table
  with its `key` (a view has none to find); needs the right to create a view there. One example, in "What it
  is not" or where a reader of "Not a transformation tool" looks next.
- **What changed in a period** (P20): the query on `<name>__log` by `_loaded_at`, with the note that an
  update shows the new values.
- **The time is the time of the run** (P20): two changes between two runs are one version; a row deleted and
  inserted again between two runs is one update. One sentence beside the history example.
- **`_loaded_at` is the last change, not the last load** (P20): a run that finds nothing writes no log row.
- **Which checks run before the staging table exists** (P23): the table "Checks before publishing" says for
  each check where it runs, so that someone adding a check knows where it goes. Read `load.py` for the truth.

In `tests/test_file.py` (P23): the helper `load()` returns success when the table is not due and nothing
loads, so a test that loads a table twice asserts nothing the second time. Make it fail when no run
happened, in the smallest way, and fix the tests that then turn out to assert nothing.

In `docs/open-points.md`: "Whether Sling or ingestr already cover most of this" gets the persona's answer as
a lead, not a fact: they cover the loading (more sources, incremental, CDC; their documentation checked on
2026-11-18), not the freshness model; the second half is from memory and unchecked.

## Acceptance criteria

- [ ] Every query and command added to the README was run and gives what the text says.
- [ ] `tests/test_file.py`, `tests/test_guide.py`, `tests/test_licences.py` pass. Do not run the whole suite: Docker's disk is small and other suites are running.

## Comments
