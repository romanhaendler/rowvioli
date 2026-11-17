# 12: What the second wave looked for in the documents and did not find

**Blocked by:** none

**Status:** resolved

**Model:** Sonnet

From the shakedown of 2026-11-17 (P16 migrating team, P20 consumer, P3 staff engineer, P23 successor). Text
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
2026-11-17), not the freshness model; the second half is from memory and unchecked.

## Acceptance criteria

- [ ] Every query and command added to the README was run and gives what the text says.
- [ ] `tests/test_file.py`, `tests/test_guide.py`, `tests/test_licences.py` pass. Do not run the whole suite: Docker's disk is small and other suites are running.

## Comments

Resolved. Each case was built and run against a scratch Postgres.

README additions:
- "What it is not" (after the list): a view with `WHERE` and renamed columns, listed as a table with its `key`; needs the right to create a view. Run: loads, changes of the view arrive as ordinary updates. Found: `rowvioli list` does not show views at all (the ticket says a view has no key to find), so the text says to write the key yourself. A changed column list of the view fails the schema check like any column change.
- "When a table is loaded" (after the bullets): `at` with `timezone` and a long `max_age`; `rowvioli status` showed `in 4h 27m` for a table loaded seconds before.
- "Target schema" (after the TEMP tables paragraph): `__log` and `__history` beside every mirror with a key, `log = false` leaves them out, and a table already there is taken over if columns, types and primary key match (the first run deleted the row the source lacked, the log began with the rest as `I`). Not in the ticket; found by trying the take-over. Nothing about `numeric(p,s)`.
- "Target schema", history example: two changes between two runs are one version; delete and insert again is one `U`, or no change when identical (both run).
- "Target schema", after the `_loaded_at` sentence: a run that finds nothing writes no log row (run: the log's newest `_loaded_at` stayed, `tables.loaded_at` moved), so it is the last change, not the last load.
- "Target schema", after the moment query: what changed in a period, a query on `<name>__log` by `_loaded_at`; update shows new values, delete the last ones. Run against a hand-built copy of the README's own example log.
- "Checks before publishing": a column "Runs" in the table. Per `load.py`: only a key column missing in the source fails before the staging table exists (new in the Key row's "Aborts if"); zero rows fails at the end of step 3 (the diagram says step 4); the share after step 5; the rest in step 4.

docs/open-points.md: the Sling/ingestr point has the persona's answer as a lead.

tests/test_file.py: `load()` now names the source (`run files`, which requests every table) and asserts the answer holds tables. All 34 tests still passed: none had asserted nothing (no test loads twice through the helper; the second loads use `files.run` with names).

Added by the coordinator: `rv.run(..., open_files=N)` in `tests/conftest.py` (soft `RLIMIT_NOFILE` set with `preexec_fn`, documented in the docstring). The 1000-files test uses it and no longer imports `ROWVIOLI` or calls `rv._env()` (it exists once, parametrized csv/jsonl). Checked with `FILES_PER_READ = 1000` in `src/` (reverted): csv failed with "Cannot open file ... Too many open files"; jsonl still passed with it, so only the csv case guards the limit.
