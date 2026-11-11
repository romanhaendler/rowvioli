# Measurements

All numbers were taken on 2026-11-11 with the scripts in `experiments/`.

## Set-up

- PostgreSQL 16 (`postgres:16-alpine`) in a Docker container on macOS, limited to 2 CPUs and 2 to 4 GB of memory.
- No tuning unless stated. `work_mem` is the default 4 MB in experiments 01 and 02 and 256 MB in 03 and 06.
- Every number is a single measurement. Expect a spread of well over 10 %.
- Experiments 1 to 6 run inside the database. Reading from a source, the network and the COPY from a client are **not** included there. "Filling the staging table" is an `INSERT ... SELECT` inside Postgres and only stands in for the write cost of a COPY. Experiment 8 is the exception: it fills the staging table from a Python client on the same machine.
- The test table has 16 columns (integers, decimals, dates, short texts), shaped after the `lineitem` table of the `hpdl` benchmark. A change set is 1 % updated, 0.1 % deleted and 0.1 % inserted rows.

## 1. Compare and publish in one transaction

Experiment `01_veroeffentlichen.sql`. This is the first variant of the design: both comparison queries run inside the publishing transaction. Staging table is unlogged.

| Step | 10⁶ rows | 10⁷ rows |
|---|---|---|
| Fill the staging table | 0.5 s | 10.6 s |
| Find deleted rows, write to change log | 0.8 s | 9.9 s |
| Find inserted and updated rows, write to change log | 1.0 s | 24.9 s |
| Apply to the mirror (delete, then insert) | 0.2 s | 24.5 s |
| **Whole publishing transaction** | **1.9 s** | **59 s** |
| Comparison only, nothing changed | 0.5 s | 13 s |
| Without a key: delete all, insert all, one transaction | 2.9 s | 40 s |

After publishing, mirror and staging table were identical row by row (`EXCEPT` returned nothing).

Applying the diff took a conspicuous 16 s for the delete step alone at 10⁷ rows. The freshly written change-log rows had no statistics at that point. Experiment 3 analyses the diff table first and the same step takes 6 s. The cause was not investigated further.

## 2. Row comparison on a wide table

Experiment `02_breite_tabelle.sql`. 900 columns (300 each of integer, `numeric(12,2)` and 8-character text), 100,000 rows, 784 MB per table. The change is placed in the last column, the worst case for a column-by-column comparison.

| Query | Duration |
|---|---|
| Join on the key only, no comparison | 0.5 s |
| `ROW(...) IS DISTINCT FROM ROW(...)` over all 900 columns, nothing changed | 5.7 s |
| The same, 1 % of the rows changed in the last column | 4.8 s |
| Alternative: `md5(s::text) <> md5(m::text)` | 9.4 s |
| Alternative: `EXCEPT` | 223 s |
| Row comparison without parallel query, `work_mem` 4 MB | 6.9 s |
| Row comparison without parallel query, `work_mem` 1 GB | 5.2 s |

What the numbers say:

- The comparison costs about as much as reading both tables once: roughly 1.5 GB in 5.7 s, or about 60 ns per compared cell. On the narrow table of experiment 1 it is about 30 ns per cell.
- Postgres turns the row comparison into 900 single comparisons joined by `OR`. This is visible in the plan.
- The hash table of the join holds the complete rows of the mirror, 590 MB here. With 4 MB of `work_mem` Postgres spills it to disk. That works, and it is why wide tables cost more per row than narrow ones.
- A hash over the row is slower than the direct comparison, because every row has to be turned into text first. `EXCEPT` is out of the question.

Not measured: a million rows of this width. Linear growth would mean about a minute.

## 3. Computing the diff before the transaction

Experiment `03_unterschiede_vorab.sql`, 10⁷ rows, `work_mem` 256 MB, unlogged staging table. The diff goes into a table of its own with `CREATE TABLE ... AS`, which allows Postgres to run the query in parallel.

| Step | Duration |
|---|---|
| Compute the diff, one core | 40 s |
| Compute the diff, two cores | 26 s |
| Publishing transaction (change log, delete, insert) | 15 s |

The publishing transaction shrinks from 59 s to 15 s and depends only on the number of changes. The final row-equality check of this script did not run (shared memory of the container). The found counts were right: 10,000 deleted, 10,000 inserted, 100,000 updated.

## 4. Killing a client

Experiment `04_harter_abbruch.sh`. A client holds an advisory lock and is ended with `kill -9`.

| Situation | Lock released after |
|---|---|
| Postgres is waiting for the next command | under 0.3 s |
| Postgres is computing a 15 s statement | still held after 2 s, released after the statement ended |
| The same with `client_connection_check_interval = 2s` | under 4 s |

Not measured: a machine or network failure, where nobody closes the connection. Postgres then notices only through TCP keepalive. The `data-extractor` project came to the same limit (ADR-0011 there: about 60 s expected with the keepalive values used, not reproducible locally).

## 5. Claiming with several workers

Experiment `05_vergabe.sql` and `05_vergabe.sh`. Two sources with `parallel` 4 and 2, 40 and 10 waiting runs, 12 workers that each claim, work for 0.15 to 0.35 s, record `ok` and release the lock. One additional worker claims a run and is ended with `kill -9`. A probe counts the held table locks per source every 20 ms.

| Observation | Result |
|---|---|
| Highest concurrency per source | 4 and 2 |
| Samples above the limit, of 600 | 0 |
| Runs by status at the end | 50 `ok`, 1 dead |
| Tables with exactly one successful run | 50 of 50 |
| The killed worker's table | recorded as dead, loaded by another worker as attempt 2 |

This is the claim of the first round: it hands out waiting runs and uses one counting lock per source. The second round claims due tables with one counting lock for the whole target and adds a total limit (decisions 20 and 29). That form is not tested. What the experiment still shows is the mechanism: limits counted from held locks hold under concurrency, and a run whose lock is gone is recognised.

## 6. Staging as a TEMP table

Experiment `06_temp_staging.sql`, 10⁷ rows, `work_mem` 256 MB, `temp_buffers` 512 MB. Staging table and diff are TEMP tables, as the design now prescribes.

| Step | Duration |
|---|---|
| Fill the staging table | 16.4 s |
| Compute the diff, two parallel workers allowed | 38.5 s |
| Publishing transaction | 16.8 s |

- After publishing, mirror and staging table were identical row by row. This verifies the variant "diff first, then apply".
- The diff takes as long as on one core in experiment 3. Postgres does not scan TEMP tables in parallel workers, so the gain from 40 s to 26 s is lost.
- Filling is slower than with an unlogged table (16.4 s against 10.6 s). `data-extractor` measured both as equal at 10⁶ rows through ADBC (ADR-0004 there: 0.42 s against 0.46 s). The difference here was not investigated.

The same script shows how `ROW(...)` compares:

- With columns named in the same order, a mirror `(id, x, y)` and a staging table `(id, y, x)` holding the same values compare as equal.
- With `ROW(b.*) IS DISTINCT FROM ROW(a.*)` the query fails with `operator does not exist: integer = text`. With compatible types it would not fail but silently compare the wrong columns.

## 7. Encrypting secrets

Experiment `07_geheimnisse.py`, PyNaCl 1.6.2. Not a timing but a check of the properties the encrypted connections rely on. The experiment encrypts a single named value. The design now encrypts a whole connection block under the name of its source (decision 26).

| Property | Result |
|---|---|
| A value encrypted with the public key decrypts with the private key | yes |
| The same value encrypted twice gives different ciphertexts | yes |
| The public key cannot decrypt | yes, the library refuses |
| One flipped bit in the ciphertext | decryption fails with `CryptoError` |
| A ciphertext presented under another name | rejected by the name check |
| Another private key | decryption fails with `CryptoError` |

A 54-byte plaintext becomes a 102-byte ciphertext.

## 8. The driver of the control connection

Experiment `08_treiber.py`, adbc-driver-postgresql 1.13.0, pyarrow 26.0.1, psycopg 3.3.8, Python client on macOS against `postgres:16-alpine` in Docker without limits. The question: can ADBC alone do everything a run needs on one connection, or is a second Postgres driver necessary?

Each variant plays two complete runs on a single connection: take a session-level advisory lock, fill a TEMP staging table with 10⁶ rows of 8 columns (integer, text, decimal, timestamp with time zone, date, boolean, float, a column of nulls), compute the diff, publish in a transaction. The second run changes 1 % of the rows. A second connection watches.

| Check | ADBC alone | psycopg 3, row by row | psycopg 3 with pgpq |
|---|---|---|---|
| Session lock taken, visible in `pg_locks` | yes | yes | yes |
| Staging table is a TEMP table, invisible to the second connection | yes | yes | yes |
| Before COMMIT the second connection sees the old state, after it the new one | yes | yes | yes |
| Lock still held after COMMIT and after ROLLBACK | yes | yes | yes |
| ROLLBACK leaves the mirror unchanged | yes | yes | yes |
| A unique violation arrives with SQLSTATE 23505, connection usable afterwards | yes | yes | yes |
| Lock gone 0.3 s after closing the connection | yes | yes | yes |
| Filling the staging table, 10⁶ rows | 0.5 s | 4.1 s | 0.5 s |
| Publishing the initial load, 10⁶ rows | 1.8 s | 1.5 s | 1.6 s |
| Computing the diff at 1 % changes | 2.3 s | 1.0 s | 1.0 s |

What the numbers say:

- **ADBC can carry the control connection alone.** Lock, TEMP tables and transaction have to be on one connection, so a second driver could not share the work anyway.
- **ADBC streams.** A query on `pg_stat_progress_copy` from the second connection, issued when the reader had handed over half of the batches, found 485,000 rows already processed by the server.
- **ADBC wraps every query that returns rows into `COPY (...) TO STDOUT`.** `SHOW lock_timeout` fails with a syntax error for that reason. `SELECT current_setting('lock_timeout')` works.
- **ADBC decides the column types of the staging table.** `decimal128(12, 2)` becomes `numeric` without precision. The comparison is not affected.
- **psycopg row by row** passes every value through a Python object and takes eight times as long to fill the staging table.
- **psycopg with pgpq** is as fast as ADBC and needs two more dependencies and a type table from Arrow to Postgres of our own.

Limitations: one measurement each. The diff at 1 % changes took 2.3 s through ADBC against 1.0 s through psycopg, which was not investigated. Not tested: a Linux client, a real network between client and server, the row counts the driver itself reports, and a target address with several nodes.

## Reference: hpdl

From `hpdl/docs/performance.md`, same table shape, source and target with 2 CPUs and 4 GB each, worker with 3 CPUs:

| Rows | Run | Duration |
|---|---|---|
| 10⁶ | initial load | 3.0 to 3.8 s |
| 10⁶ | unchanged | 0.8 to 0.9 s |
| 10⁶ | 1 % changed | 1.2 to 1.4 s |
| 10⁷ | initial load | 30 to 43 s |
| 10⁷ | unchanged | 8.3 to 10 s |
| 10⁷ | 1 % changed | 25 to 42 s |

These are complete runs including reading from the source, so they are not directly comparable with the numbers above. They show the order of magnitude: the simple path is in the same range at 10⁶ rows and clearly slower at 10⁷, where staging (16 s), diff (39 s) and publishing (17 s) add up to more than a minute before any reading.

The bottleneck in `hpdl` was never the Python worker: source CPU on unchanged runs, target CPU on initial loads, a single target session on merges. This is the reason the choice of language does not decide the speed.

## Summary

| Claim | Evidence |
|---|---|
| Publishing leaves mirror equal to the source | experiments 1 and 6 |
| Consumers never see an empty table | follows from one transaction and MVCC. Not tested with a concurrent reader. |
| The row comparison scales with the amount of data, not abruptly with the column count | experiment 2 |
| The per-source limit holds under concurrency | experiment 5 |
| A dead run is detected | experiment 5. The retry after a growing pause is not tested. |
| One driver can do everything a run needs on one connection | experiment 8 |
| Nothing is visible to another connection before the COMMIT | experiment 8, without a reader running alongside |
| A killed process releases its lock | experiment 4 |
| Connections cannot be read without the private key, and tampering is detected | experiment 7, with a single value in place of a block |
| A killed process cannot publish | follows from the transaction ending with the connection. Not tested as such. |
