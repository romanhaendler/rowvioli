# Decisions

Every decision of the concept with its reason, its price and what was rejected. The order follows the discussion of 2026-11-11, so the document also shows how the design got to where it is.

Evidence refers to `docs/measurements.md` and to the earlier projects `hpdl`, `data-extractor` and `dataly` in the same workspace.

## Starting point

Three earlier attempts exist: `hpdl` (Python worker, hash comparison per key range, SCD2), `data-extractor` (a specification in its sixth review round with 22 ADRs) and `dataly` (dlt and dbt behind a service with its own scheduler). None was satisfying.

The first idea for a new attempt was a very fast Rust program. The discussion showed that speed was not the problem. The problem was complexity: load modes, hashes, key ranges, partitions, views, fencing tokens. The goal of this concept is therefore **half as many concepts**, with speed as a constraint and not as the aim.

## 1. PostgreSQL is the only target and the only place of coordination

**Decision.** The program loads into PostgreSQL only. Orders, runs, locks and status live in the target database. There is no other state: no state file, no broker, no service that has to be reachable.

**Why.** All earlier projects loaded into Postgres. Session locks, transactions and the system view `pg_locks` give locking, dead-run detection and counting without building anything.

**Price.** Other targets are out. A note in `data-extractor` (`docs/notiz-weitere-ziele.md`) examined which of these mechanisms other databases offer; Azure Database for PostgreSQL has all of them, Fabric and Databricks do not.

## 2. Compare in the target, by row comparison

**Decision.** Every run writes the complete source table into a staging table in the target. Postgres finds the differences with a join and `ROW(...) IS DISTINCT FROM ROW(...)`.

**Why.** No hash, no canonical text form of values, no type normalisation in the program. The comparison happens in the target types, where it is exact. The program stays a pipe.

**Price.** Every run writes the whole table once, even if nothing changed. At 10⁷ rows the path is slower than `hpdl`.

**Rejected.**
- *Hash per row in the worker* (as in `hpdl` and `data-extractor`). Faster for large tables, but brings the hash definition, its recomputation after type changes and key ranges for bounded memory.
- *A stored hash column in the mirror.* Would roughly halve the comparison on wide tables because only key and hash of the mirror are read. Kept in reserve for a concrete table that is too slow.
- *`EXCEPT`.* 40 times slower on a wide table.
- *Sorted merge of two ordered streams.* Needs identical sort order in source and target, which collations do not guarantee.

## 3. One flow instead of load modes

**Decision.** Initial load, follow-up load and tables without a key take the same path: staging, compare, apply in one transaction. There is no `append`, `scd1`, `scd2`, `replace` or `snapshot`.

**Why.** Every mode is a code path of its own with its own edge cases. One path can be tested completely.

**Price.** The initial load writes twice (staging table, then mirror). Tables without a key are deleted and re-inserted on every run, which bloats the table until autovacuum has cleaned up.

**Rejected.**
- *Swapping tables by renaming or attaching a partition.* Needs an exclusive lock that long-reading consumers block, and breaks dependent views. `data-extractor` spent several ADRs on this (0007, 0019, 0021).
- *`TRUNCATE` and reload.* Not safe under MVCC: a concurrent reader can see an empty table.
- *Views that switch to a published run number.* Only needed when several transactions write the same table in parallel, which this design does not do.

## 4. Mirror plus change log instead of a history table

**Decision.** The target table is an exact mirror. An optional second table records per run what was inserted, updated and deleted, and only ever grows.

**Why.** Consumers read a normal table without validity columns, views or filters. The diff exists anyway, so the change log costs one more insert. History is not a mode but a by-product.

**Price.** Validity periods (SCD2) have to be computed by a view over the change log. Its speed on a long history is not measured. Tables without a key have no change log.

## 5. Compute the diff before the transaction

**Decision.** The diff goes into a small table first. The publishing transaction only applies it.

**Why.** The expensive part moves out of the transaction. At 10⁷ rows the transaction shrinks from 59 s to about 15 s and depends only on the number of changes. Long transactions hold back vacuum and keep locks.

**Why it is safe.** As long as the run holds the table lock, no other run changes the mirror between comparison and publishing.

**Price.** Anyone who writes to a mirror by hand, bypassing the lock, can make a diff stale. Mirrors are written by the program only.

## 6. Staging and diff are TEMP tables on the control connection

**Decision.** A run uses exactly one connection to the target for everything. Staging table and diff are TEMP tables on it.

**Why.** No naming scheme, no clean-up, no leftovers of dead runs: the tables disappear with the connection. `data-extractor` came to the same conclusion (ADR-0004) and measured the same COPY throughput as with unlogged tables.

**Price.** Postgres does not scan TEMP tables in parallel workers. The gain measured with an unlogged staging table (40 s down to 26 s at 10⁷ rows on two cores) is lost. In the working range of up to 10⁶ rows this is irrelevant. Parallelism comes from loading several tables at once.

**Rejected.** *Unlogged staging tables with a fixed name.* This was the design until the write-up. It needs a second connection, names per run and a clean-up step for dead runs.

**To be revisited** if a single large table has to get faster.

## 7. The lock hangs on the connection, and publishing happens on that connection

**Decision.** A session-level advisory lock per target table, taken on the control connection. The publishing transaction runs on the same connection.

**Why.** If the process dies, connection, lock and open transaction are gone together. A zombie cannot commit, because a COMMIT needs a command from a client that no longer exists. This makes a fencing token unnecessary. `data-extractor` needed one (ADR-0010) because several connections wrote the same table.

**Price.** The control connection must reach Postgres directly, not through a pooler in transaction mode. Advisory locks share one number space per database with every other application that uses them. During a long statement Postgres notices a dead client only with `client_connection_check_interval`. After a machine or network failure, release depends on TCP keepalive.

## 8. Every table on its own

**Decision.** Each table has its own lock, its own run and its own transaction.

**Why.** A broken table does not hold up the others. Parallelism and distribution over machines become simple. This was the user's correction of an earlier draft.

**Price.** Tables of one source are published at different moments. For a short time `orders` can be new while `customers` is old.

**Rejected.** *All tables of a source in one transaction.* Gives a consistent state across tables, but one failing table blocks all, the transaction gets long, and the work cannot be spread over workers. If cross-table consistency is ever needed, it would be an explicit group of a few tables, not the default.

## 9. One file per source with include and exclude

**Decision.** A source file holds the connection once, patterns for tables, and overrides for single tables.

**Why.** With 200 tables in an ERP system, one file per table means 200 near-identical files and soon a wish for defaults and inheritance. `hpdl` already had layered settings for that reason.

**Price.** With a pattern like `dbo.*`, new tables in the source appear in the target automatically. A connector needs a second function that lists tables and keys.

**Rejected.** *One file per table*, the earlier draft.

## 10. Orders in Postgres, workers pull

**Decision.** A submitter writes an order into a table. Workers claim waiting runs themselves. `run` is the small case: it creates the order and works it off in the same process.

**Why.** Horizontal scaling means starting another worker. Nobody distributes tables over machines. The scheduler needs only database access and can even insert the order as SQL. A web UI can start loads. The per-source limit holds across workers and orders.

**Price.** From the second machine on, a permanently running service exists that somebody has to supervise. Two more terms: order and the status `waiting`.

**Rejected.**
- *The scheduler calls a specific machine.* The earlier draft. It does not scale without the scheduler knowing the machines.
- *Static split of tables over machines.* No coordination, but uneven load, and a failed machine leaves its share unloaded.
- *Exit code 75 for "already running".* Dropped. A duplicate order queues up instead of being rejected.

This is not a scheduler. Nothing in the program knows about time.

## 11. Count held locks instead of keeping a counter

**Decision.** The number of tables of a source that are loading is the number of its table locks in `pg_locks`. A short lock per source serialises counting and claiming.

**Why.** A counter has to be decremented, and a dead worker does not decrement. Held locks cannot be wrong. The same view detects dead runs: recorded as running, lock missing.

**Price.** The lock key carries meaning (source number, table number), and number 0 is reserved.

**Evidence.** Experiment 5.

## 12. Python, not Rust

**Decision.** The core is written in Python.

**Why.**
- The data path runs through native libraries (Arrow, ADBC, arrow-odbc, DuckDB). The core hands chunks from one to the next. There is nothing to speed up.
- In `hpdl` the bottleneck was never the worker but source and target.
- A connector becomes two Python functions. For REST interfaces that is the natural language.
- Informix needs the IBM ODBC driver on the machine in any language, so "one static binary" does not hold for that source anyway.

**Price.** Python and the drivers have to be present on every worker. A Rust binary would have had a fixed memory footprint and no runtime.

**Rejected.** *Rust core*, the starting idea. Also considered: a Rust core with connectors as subprocesses that write Arrow IPC to stdout. More moving parts for no measured gain.

## 13. A connector is two functions, reachable in three ways

**Decision.** `tables(cfg)` and `read(cfg, table)`. `read` may yield Arrow batches or lists of dicts. Connectors are found through Python entry points; the shipped ones use the same mechanism. Heavy dependencies are optional extras. A file in the jobs repo works without any packaging.

**Why.** Not everybody needs every connector. Writing one must be possible in a few lines.

**Price.** As soon as outside packages build on the two functions, they can no longer be changed freely. Types inferred from dicts can flip between runs.

**Rejected.** *A separate package per shipped connector from the start.* Five packages mean five releases and version alignment. The mechanism allows it later without a change for users.

## 14. Definitions in a Git repo, delivered by `git pull`

**Decision.** Source files, custom connectors, the schedule and the pinned program version live in one repository. A load host has a checkout that is updated every few minutes.

**Why.** The scheduler only has to be able to start a command. Program version and source files are in the same commit. A deployment ends no process: a worker reads the source file only when it starts a table, so a new source never interrupts a running load. Only a new program version needs a restart, and that happens between two tables.

**Price.** After a change, workers run with different states for a few minutes. Drivers are installed by hand once per machine.

**Rejected.** *A container image as the unit of delivery.* The scheduler would have to pull and start images, which is not a given.

## 15. Source secrets are stored in the target, encrypted for the workers

**Decision.** A source file names a secret. The connection string is stored in `_rowvioli.secrets`, encrypted as a libsodium sealed box with a public key. Only workers hold the private key, as a file on the load host. The public key is in the jobs repo. If the store has no entry, the environment variable of that name is used.

**Why.**
- A new source reaches every worker at once, with no file to distribute and no restart. This holds for machines and containers alike. Environment variables of a container cannot change after it has started.
- Everything else is coordinated through the target already.
- Asymmetric encryption separates setting from reading. A person or a web UI can set a secret with the public key and can never read one back, so the decryption key does not spread to laptops.
- The same source file runs unchanged against test and production. Nothing secret is in Git.

**How it is made solid.**
- A standard construction through a standard library, nothing assembled by hand.
- The name is encrypted together with the value, so a ciphertext cannot be moved to another name.
- The public key comes from the jobs repo, not from the database.
- The private key is a file with mode 600, never the value of an environment variable.
- Decrypted values stay in memory and are removed from error texts before those are stored.

**Price.** Secrets are in the target database and in its backups, though encrypted. One key pair has to be managed and rotated. A compromised load host can read every secret. One more dependency (PyNaCl) and three more commands.

**Rejected.**
- *A secrets file on every load host, read at the start of each run.* The state for a few hours on 2026-11-11. It works on machines and with mounted files in containers, but the password still has to be distributed to every host by a separate path.
- *Environment variables exported at worker start.* The first version. A running worker never sees the password of a new source.
- *Symmetric encryption with one shared key* (Fernet or AES-GCM). Whoever sets a secret would need the key that also decrypts all of them.
- *Encrypting inside Postgres with pgcrypto.* The key would travel to the server in a query and could end up in its logs.

**Evidence.** Experiment 7 for the encryption. The store around it is not built.

## 16. No official Docker image

**Decision.** The project ships an example Dockerfile, no image.

**Why.** A useful image needs the ODBC drivers of Microsoft and IBM, which are under vendor licences and do not belong into an MIT project. `data-extractor` decided the same (ADR-0012).

## 17. Schema changes: additive automatically, everything else stops

**Decision.** A new column in the source is added to the target. A missing column or a changed type fails the run and leaves the target unchanged.

**Why.** Adding is safe. Everything else needs a person who decides what happens to existing data.

**Price.** Adding a column takes a short exclusive lock that a long-reading consumer can block. A `lock_timeout` turns that into a failed run.

## 18. Safety limits before publishing

**Decision.** A run aborts if the source delivers zero rows or more than `max_delete_share` (default one half) of the rows would disappear.

**Why.** "Consistent" is not enough. A broken source would empty the mirror in a perfectly consistent transaction. `dataly` has the same rule.

## 19. A worker claims only what it can load

**Decision.** Before claiming, a worker determines the sources for which it has the source file in its checkout and a secret it can decrypt. It passes this list to the claim, which hands out only runs of those sources.

**Why.** After a new source is merged, workers pull it at different moments. Without this rule, a worker that is behind would claim a table of the new source and fail it. With it, adding a source needs no restart and no coordination: each worker starts serving the source as soon as it has both parts.

It also allows workers that reach only some sources, for example one inside a separate network zone.

**Price.** If no worker has both parts, the runs wait without any error. The status view has to show waiting runs that no running worker offers to load.

**Evidence.** None yet. The claim function in experiment 5 has no such filter.

## Not examined

- **Ready-made tools.** Whether Sling or ingestr already cover most of this was never checked.
- **DuckDB as the engine.** DuckDB reads Postgres, CSV, Excel and JSON and can write to Postgres. The program would then be little more than SQL with a thin shell for lock and publishing. Whether it attaches MSSQL and Informix usefully is unknown. In this concept DuckDB is only the `file` connector.

## Corrections made while writing this up

The write-up reviewed the sketches from the discussion. These points differ from the pages linked in the README:

| Point | Before | Now |
|---|---|---|
| Staging table | unlogged table with a name per run, cleaned up after dead runs | TEMP table on the control connection (decision 6) |
| Connections per run | control connection plus a data connection | one |
| Source setting | `connection_env` | `connection_secret` |
| Row comparison | `ROW(s.*) IS DISTINCT FROM ROW(m.*)` | columns named explicitly; `*` compares by position and breaks after a column is added (experiment 6) |
| `run` | claims any waiting run | claims only runs of its own source and ends with its order |
| Types | "follow from the Arrow schema" | still true, but each connector has real mapping work, for example `numeric` through ADBC |
| Counting query | filtered on source only | also on the current database |
| Exit codes | 0, 1, 75 | 0 and 1 |
| Change log for tables without a key | not stated | none |
| Secrets | exported into the worker's environment at start | encrypted in the target, decrypted at the start of every run (decisions 15 and 19) |
| Names | `etl`, `_etl`, German column names | `rowvioli`, `_rowvioli`, English column names |
