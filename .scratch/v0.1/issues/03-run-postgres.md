# 03: `run` end to end with the `postgres` connector

**Blocked by:** 02

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli run [<source> [<table>]]` loads everything due (or the named scope, regardless of age, by setting `requested_at`) and ends when nothing in its scope is due and nothing is loading. It is the one worker loop (also used later by `work`): ask every two seconds what is claimable, start a fresh process per table; the run process claims under the counting lock as README "How Postgres counts" shows (most overdue first), reports its claim to the worker before reading, opens the connection, calls the connector, fills a TEMP staging table chunk by chunk through ADBC ingest, computes the diff, and publishes mirror, change log, `loaded_at`, `attempts = 0` and its `runs` row (with the definition hash copied from `meta` at claim) in one transaction. The first run creates the target schema under an advisory lock and the mirror and change log inside the publishing transaction. A table without a key is replaced as a whole and has no change log; `log = false` gives no change log; composite keys work. Column lists by name, never `*` or by position. A failed run writes its reason to the table and `runs`, then closes (status first, then the lock). Connectors are found through the entry point group `rowvioli.connectors`; `postgres` registers that way, reads through ADBC as batches and maps `numeric` to `decimal128(p, s)` (`decimal256` beyond 38 digits). `run` prints one JSON object (duration; per target table `status` and counts or `reason`) and exits 1 if a table failed. `run`/`work` name a missing `ROWVIOLI_TARGET_URL` or `ROWVIOLI_KEY_FILE` at start; `run <source> <table>` with an unknown or disabled name exits 1 before anything is loaded.

- [x] The prototype's `test_run` suite passes (adapted: unknown table now fails)
- [x] `run` and `work` without either variable end at once naming it (spec test 7)
- [x] `run <source> <table>` with an unknown or disabled name exits 1 and loads nothing (spec test 8)
- [x] `log = false` gives no change log (spec test 13, first part)
- [x] A composite key mirrors and logs correctly (spec test 14)
- [x] Every run carries the hash of the definition applied before it (spec test 19)

## Comments

Where the later tickets plug in:

- **Loop** (`work.py`): `loop(slots, source, table, once)` asks `ASK` (claimable count from `sql/claimable.sql`, plus "due or loading" in scope), starts `python -m rowvioli.load <worker> <source> <table>` per claimable table, and reads each process's JSON lines in `listen`. The claim line carries `run` and `max_seconds` for 07; 07 adds the clock, SIGTERM and reconnecting there. `work` is already wired to `loop(slots)` without those.
- **Run** (`load.py`): `main` → `claim` → `load` (stage, diff, publish) or `fail`. 04 puts its checks into `load` between staging and diff and after the diff, and adds columns in `publish`. 05 scrubs in `fail` (the one place a reason is written) and in `main`'s `except`; `seal.unseal` already picks the private key by `key_id` and checks the source name, and the reasons for a missing connector or an undecryptable connection already name the worker.
- **Connectors** (`contract.py`): `connector(type)` loads the module registered in the entry point group `rowvioli.connectors`. 08 adds `file = "rowvioli.connectors.file"` to `pyproject.toml`.

Decided here, small:

- Options reach the connector as the source's options overridden by the table's (`(s.options || t.options)`). One sentence added to the README.
- `run <source>` with an unknown source exits 1 like an unknown table: the rule is "the name matches no enabled table".
- A run process that dies before claiming makes `run` start no more processes and exit 1 (prototype E10).
- A connector that returns an iterator with no batch at all fails with "the source delivered zero rows" (the staging table needs a schema). For a `RecordBatchReader` with zero rows the zero-rows check of 04 applies.
- A change log missing on a table with a key and `log = true` is created at publishing, so switching `log` back on works.
- Reasons are not scrubbed yet (05); a run process that dies prints its traceback to stderr (05).
