# Measurements

All numbers were taken on 2026-11-11 with the scripts in `experiments/`, except section 9, which was taken on 2026-11-12 with the throwaway prototype.

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

This is the claim of the first round: it hands out waiting runs and uses one counting lock per source. The second round claims due tables with one counting lock for the whole target and adds a total limit (decisions 20 and 29). That form was tested by the prototype (section 9). What this experiment still shows is the mechanism: limits counted from held locks hold under concurrency, and a run whose lock is gone is recognised.

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

## 9. The prototype

Source: `.scratch/prototype/findings.md`, with the code and its tests on branch `prototype-impl` (62 passed). A laptop with Apple Silicon against `postgres:16` in Docker, Python 3.13, adbc-driver-postgresql 1.13.0, pyarrow 26.0.1, PyNaCl 1.6.2. The prototype plays the whole model: `init`, `key new`, `apply`, `run`, `work`, the status view, the claim, both limits and the pause.

A process per run, 10 repetitions each, median. A 100-row table with a key, nothing changed:

| What | Median |
|---|---|
| Bare `python -c pass` | 0.013 s |
| Python plus importing pyarrow, ADBC and PyNaCl | 0.105 s |
| A run process that claims nothing: start, import, connect, claim query | 0.183 s |
| The run inside the target, claim to publish | 0.068 s |
| `rowvioli run erp public.customers`, wall time | 0.453 s |

The status view and the claim's pick, with 10 table locks held:

| Tables | `select * from status` | the claim's pick |
|---|---|---|
| 2 | 0.3 ms | 0.4 ms |
| 200 | 1.1 ms | 1.3 ms |
| 1000 | 3.7 ms | 4.2 ms |

Lock released after `kill -9` of a run process:

| The run's backend was | Lock released after |
|---|---|
| waiting for the client, while filling | about 10 ms |
| waiting for a lock, at the diff or while publishing, with `client_connection_check_interval = 2s` | about 2 s |

Both limits under concurrency: 6 workers with 4 slots each, erp with `parallel = 2`, crm with `parallel = 3`, 10 slow tables each, `max_running = 4`, a probe on `pg_locks` every 20 ms.

| Variant | Result |
|---|---|
| With the counting lock | never more than 2 erp, 3 crm or 4 in total; 2 erp and 4 in total were reached |
| Counting lock replaced by `SELECT 1` | the total limit broke in 1 of 4 runs (5 locks against 4), and in 2 of 3 runs in an earlier series |
| Smaller load (3 workers, 2 × 5 tables), without the counting lock | never broke the limit |

What the numbers say:

- **A process per run costs about 0.18 s** before it does any work, more than twice the work for a small table. That is irrelevant for tables loaded every few minutes. Decision 25 had assumed half a second.
- **The view and the claim stay cheap.** 4 ms per claim, serialised by the counting lock, allows about 250 claims a second. The one part that grows with tables times locks is the look into `pg_locks` per table.
- **The counting lock is what holds the limits.** Without load the race is rare, because claims have to overlap within a few milliseconds and starting a Python process spreads them out. A probe at low load proves nothing.
- **`client_connection_check_interval` also works during a lock wait.** Both release times stay within the README's "Failures" table.
- **The driver hands over batches of about 16 MB**, or the rest at the end of the stream. A small table arrives as one batch.

Every number is a single series on a laptop. Not measured: a Linux client, a real network, and a machine failure (section 11 cuts a container's network).

## 10. A composite key

2026-11-12, `bench/bench.py` at 10⁶ rows through the program, twice with the key `id` and twice with the key `(linenr, id)`, whose first column has only 7 values. Same laptop and container as section 9 (2 CPUs, 4 GB). Server time of the step, the whole run in brackets, the two series as a range:

| Case | key `id` | key `(linenr, id)` |
|---|---|---|
| Comparison when nothing changed | 1.8 to 2.1 s (7.0 to 7.5 s) | 2.6 s (7.7 s) |
| Computing the diff at 1 % changes | 1.3 s (6.5 to 6.6 s) | 2.2 to 2.3 s (7.6 to 8.0 s) |
| Publishing at 1 % changes | 0.3 s | 0.2 to 0.3 s |

The second key column costs about a second on the diff of 10⁶ rows, a sixth of the whole run. Publishing does not change. The bench script was changed for this in its definition only (`key = ["linenr", "id"]`); a key `(linenr, part)` is not unique after the bench's inserts.

## 11. A worker whose network is cut

2026-11-12, two `postgres:16-alpine` containers on one Docker network on the same laptop: a target, and a client whose `psql` takes `pg_advisory_lock(1, 1)` and then stays idle. `docker network disconnect` cuts the client's network, and the target is asked every 5 seconds whether the lock is still held. One run each:

| The client's session first sets | Lock released |
|---|---|
| nothing | still held after 240 s; the server's default is two hours on Linux |
| `tcp_keepalives_idle = 30`, `tcp_keepalives_interval = 10`, `tcp_keepalives_count = 3`, `tcp_user_timeout = 60000` | after 62 s |

The keepalive in a libpq URL acts on the client's socket only, so the program sets the second row on every control connection (`target.SESSION`). The client was idle; a session in the middle of a `COPY` was not tried, nor a real machine or network.

## 12. A target address with several nodes

2026-11-12, two local `postgres:16-alpine` servers, the first with `default_transaction_read_only = on`. With `postgresql://…@127.0.0.1:<first>,127.0.0.1:<second>/postgres?target_session_attrs=read-write`, `rowvioli init` created `_rowvioli` on the second server and `rowvioli status` read it there. Without `target_session_attrs`, `status` reached the first server and found no schema. A failover was not tried.

## 13. The history view on a long change log

2026-11-13, `bench/history.py 100000 400`. The same laptop and container as section 9 (Apple Silicon, `postgres:16-alpine` with 2 CPUs and 4 GB, PostgreSQL 16.15). The log was built by 400 real runs of the program (`rowvioli run`, one process each) against a source table `lineitem (id bigint primary key, qty int, comment text)` of 100 000 rows. Before each run after the first, 1 % of the rows (`id % 100 = run % 100`) were updated, so every key has 5 versions. Result: a change log of 499 000 rows (48 MB), 400 moments, and a history view of 499 000 rows; at the moment of the 201st run the view shows 100 000 rows. The whole build took 4 min 46 s. Each time is the median of three `EXPLAIN (ANALYZE)` runs of `SELECT *`, so it excludes sending the rows. The index is the one a person might create, `CREATE INDEX ON raw_bench.lineitem__log (id, _loaded_at)`, followed by `ANALYZE`; the run builds none.

The direct query for one moment, per key the last log row up to the moment, leaving out the keys whose last row is a delete:

```sql
SELECT * FROM (SELECT DISTINCT ON (id) * FROM raw_bench.lineitem__log WHERE _loaded_at <= :moment
               ORDER BY id, _loaded_at DESC) l WHERE _op <> 'D'
```

The script checks before timing that it returns the same rows as the view with `WHERE _valid_from <= :moment AND (_valid_to > :moment OR _valid_to IS NULL)` (`EXCEPT ALL` both ways on the table's columns: no difference).

| Query | No index | Index on (id, _loaded_at) |
|---|---|---|
| The whole view | 314.5 ms | 304.6 ms |
| The view at one moment | 304.5 ms | 286.9 ms |
| The view for one key (`WHERE id = 5000`) | 8.9 ms | 0.1 ms |
| The direct query for the same moment | 116.9 ms | 122.0 ms |

What the numbers say:

- **A condition on the key is pushed below the window**: the view for one key reads one key's rows only, and an index on (key, `_loaded_at`) turns a scan of the log (8.9 ms) into an index scan (0.1 ms).
- **A condition on a moment is not**: the view at one moment costs as much as the whole view, because the window runs over the whole log first. The index changes nothing there (305 against 287 ms is noise).
- **The direct query is 2.6 times faster than the view at the same moment without an index** and unchanged by the index: it still reads the whole log, but sorts it once and has no window. Its cost grows with the log, not with the size of the answer.

Limitations: one series, one key shape (a single `bigint` column), versions spread evenly over all keys, a log that fits in memory (48 MB, cached), no concurrent writes. A log some hundred times larger, or one whose rows do not fit in memory, was not measured.

Recommendation: the README names an index, and says it is for one key and a person's choice (a run never builds it): `CREATE INDEX ON <schema>.<table>__log (<key columns>, _loaded_at)`. It also names the direct query above for one moment, with `:moment` replaced and the key columns in `DISTINCT ON` and `ORDER BY`, as the faster way to ask for a moment; the view stays the answer for the versions of one key and for all of history. It names no index for a moment, because none helps.

## 14. The pooler check behind pgbouncer in transaction mode

2026-11-15, PgBouncer 1.26.1 (`edoburu/pgbouncer`, `POOL_MODE=transaction`, pool of 5) in front of `postgres:16-alpine`, by hand, once. The control connection asks `pg_backend_pid()` in two transactions (autocommit) and fails when the two differ.

- **An idle pooler is not detected.** One client alone gets the same server connection every time (ten transactions, one pid), so the check passes and `rowvioli init` works.
- **A pooler shared with other clients is detected.** With 8 other clients running `pg_sleep(0.05)` through the pooler, 84 of 100 checks saw two different pids; 16 saw the same one.
- **The pooler fails by itself under load.** With busy neighbours the driver's prepared statements also broke (`unnamed prepared statement does not exist`, `SQLSTATE 26000`) in 2 of 12 `init` runs, before and apart from the check.

Limitations: one pooler version, one pool size, a synthetic load. A pass is no proof that no pooler is in front; the check catches the case it is built for, a pooler whose server connections are shared between clients, with a chance that grows with their number. Session mode was found to work in the shakedown (`install-target.md`).

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
| Consumers never see an empty table | prototype, with a reader running alongside |
| The row comparison scales with the amount of data, not abruptly with the column count | experiment 2 |
| The limits per source and per target hold under concurrency | experiment 5 for the earlier form, prototype for the current one |
| A dead run is detected and retried after the pause | experiment 5, prototype |
| One driver can do everything a run needs on one connection | experiment 8 |
| Nothing is visible to another connection before the COMMIT | experiment 8, without a reader running alongside |
| A killed process releases its lock | experiment 4 |
| Connections cannot be read without the private key, and tampering is detected | experiment 7. The prototype sealed whole blocks and rejected a copied ciphertext and a wrong private key. |
| A killed process cannot publish | prototype: killed while filling, at the diff and while publishing, the mirror stayed unchanged |
| A process per run costs 0.1 to 0.2 s | prototype |
| A transaction-mode pooler shared with other clients is caught by two `pg_backend_pid()` reads; an idle one is not | experiment 14 |
