# `run`: one table from source to mirror

Status: resolved
Blocked by: 02

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

The thin end-to-end slice: worker loop (one function, later shared with `work`), a fresh process per run, claim on the control connection, opening the sealed connection, connector registry with `postgres`, TEMP staging, diff, publishing with mirror creation and change log, the JSON answer and exit code of `run`, `run <source>` and `run <source> <table>`. Spec sections "Worker loop and claim", "One run", "Connector", "Answer of run". Only what a successful run needs; checks and failure paths belong to tickets 04-06, but a failing run must already record `failed` with a reason and exit code 1.

## Acceptance criteria

- [ ] Spec tests 5, 6, 7, 8, 21 pass.
- [ ] Rest of spec test 4: a disabled table is not loaded again, its mirror stays.
- [ ] `status` shows `ok` after a run; `runs` has one row per run with worker, start, end, status, counts.

## Comments

Observations for spec questions 4 and 5 (impl-03, adbc-driver-postgresql 1.13.0, pyarrow 26, Postgres 16):

- **Row counts (q4).** `cursor.rowcount` is right for `INSERT`, `UPDATE`, `DELETE` and `CREATE TABLE AS`; it is -1 for other statements. `adbc_ingest` returns the number of rows written. So `rows_read` and the counts of a table without a key come from the driver; with a key they come from `SELECT _op, count(*) FROM _diff`.
- **`numeric` (q4).** The driver reads `numeric` as an Arrow extension type `arrow.opaque[storage_type=string, type_name=numeric]`, with field metadata `POSTGRESQL:type = numeric` and `POSTGRESQL:typmod`. Ingesting that, or plain strings, with `mode="create"` gives a `text` column. Appending strings into an existing `numeric` column fails: "COPY Writer from Arrow type 'string' to PostgreSQL numeric is not implemented". What works: the `postgres` connector casts the string storage to `decimal128(p, s)` from the typmod (`decimal256` above 38 digits, `decimal256(76, 38)` for an unconstrained `numeric`). The staging column is then `numeric`, and values are equal (spec test 8, including 30 integer digits and 30 decimal places). The precision and scale are lost: source `numeric(12,2)` becomes `numeric` in the mirror, because ingest creates `numeric` without a typmod. An unconstrained `numeric` with more than 38 digits on either side of the point fails the run (shortcut in `connectors.py`).
- **Other types seen on the way.** `text[]` arrives as `list<string>`, `bytea` as `binary`, and the control connection fetches `bytea` as `bytes` and `text[]` as a Python list. `None` binds as a parameter. One statement per `execute` ("cannot insert multiple commands into a prepared statement").
- **Mirror creation inside publishing (q5).** Works: `CREATE TABLE mirror (LIKE _stage, PRIMARY KEY (key))` and `CREATE TABLE mirror__log (_run bigint, _op text, LIKE mirror)` inside the publishing transaction, from the types the driver chose for the TEMP staging table. Consumers never see the mirror before COMMIT.
- **But not the schema.** Two first runs of tables of one source, at the same time, both ran `CREATE SCHEMA IF NOT EXISTS raw_erp` and one failed with a unique violation on `pg_namespace`. An advisory lock taken inside the publishing transaction did not help: after waiting for a lock inside a transaction block, Postgres still used its cached "no such schema" from the earlier `to_regclass`, and failed again. The run now creates the schema in its own autocommit statement under a session advisory lock on `hashtext(schema)`, before the publishing transaction. An empty schema can therefore exist without a mirror; the mirror itself still never exists empty.

Deviations from README / GLOSSARY / decisions / spec:

- The README's answer of `run` has `step` for a failed table. The answer has `status` and `reason` only.
- The spec's "most overdue" is `(now() - due_at) / max_age`. Postgres cannot divide an interval by an interval; the claim uses `extract(epoch ...)` on both. The notes of ticket 01 suggested ordering by the interval quotient directly; that does not run.
- A table without a key reports `inserted` = rows written and `deleted` = rows that were in the mirror, `updated` = 0. The README says nothing about counts for it.
- `run` has `--slots` (default 4), like `work`. The README gives `run` no option. Several due tables are loaded in parallel.
- `run <source> [<table>]` sets `requested_at = now()` in scope and then runs the same loop restricted to that scope, as the README says. Naming a table that does not exist or is disabled prints an empty `tables` and exits 0.
- `run` waits for tables in its scope that are loading by another worker, as the spec says ("nothing is loading"). A request made during one of its own runs makes it load that table once more before it ends.
- The worker passes its id (host:pid of the worker process) to the run process; `runs.worker` names the worker, not the run's own process.
- The process of a run is `python -m rowvioli _load <worker> <source> <table>`, a hidden command.
