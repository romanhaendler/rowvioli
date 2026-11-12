# 03: `run` end to end with the `postgres` connector

**Blocked by:** 02

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli run [<source> [<table>]]` loads everything due (or the named scope, regardless of age, by setting `requested_at`) and ends when nothing in its scope is due and nothing is loading. It is the one worker loop (also used later by `work`): ask every two seconds what is claimable, start a fresh process per table; the run process claims under the counting lock as README "How Postgres counts" shows (most overdue first), reports its claim to the worker before reading, opens the connection, calls the connector, fills a TEMP staging table chunk by chunk through ADBC ingest, computes the diff, and publishes mirror, change log, `loaded_at`, `attempts = 0` and its `runs` row (with the definition hash copied from `meta` at claim) in one transaction. The first run creates the target schema under an advisory lock and the mirror and change log inside the publishing transaction. A table without a key is replaced as a whole and has no change log; `log = false` gives no change log; composite keys work. Column lists by name, never `*` or by position. A failed run writes its reason to the table and `runs`, then closes (status first, then the lock). Connectors are found through the entry point group `rowvioli.connectors`; `postgres` registers that way, reads through ADBC as batches and maps `numeric` to `decimal128(p, s)` (`decimal256` beyond 38 digits). `run` prints one JSON object (duration; per target table `status` and counts or `reason`) and exits 1 if a table failed. `run`/`work` name a missing `ROWVIOLI_TARGET_URL` or `ROWVIOLI_KEY_FILE` at start; `run <source> <table>` with an unknown or disabled name exits 1 before anything is loaded.

- [ ] The prototype's `test_run` suite passes (adapted: unknown table now fails)
- [ ] `run` and `work` without either variable end at once naming it (spec test 7)
- [ ] `run <source> <table>` with an unknown or disabled name exits 1 and loads nothing (spec test 8)
- [ ] `log = false` gives no change log (spec test 13, first part)
- [ ] A composite key mirrors and logs correctly (spec test 14)
- [ ] Every run carries the hash of the definition applied before it (spec test 19)
