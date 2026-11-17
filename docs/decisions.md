# Decisions

Every decision of the concept with its reason, its price and what was rejected. The order follows the discussion of 2026-11-11, so the document also shows how the design got to where it is.

There were two rounds on that day. Decisions 1 to 19 are the first round. The second round (decisions 20 to 30) replaced the model of orders, a jobs repo and an external scheduler with a maximum age per table, definitions in the target and stateless workers. Decisions of the first round that no longer hold are marked and kept, with their text unchanged. A third round (decisions 32 to 35) followed on 2026-11-12, after a throwaway prototype had tried out the model of the second round. A fourth round (decision 36) added load times, a fifth (decision 37) the lines of a worker, a sixth (decision 38) the rule for licences, a seventh (decisions 39 and 40) target names and history. An eighth (decisions 41 to 43) followed on 2026-11-15, after the shakedown of the built wheel.

Evidence refers to `docs/measurements.md`.

## Starting point

The first idea was a very fast Rust program. The discussion showed that speed was not the problem. The problem was complexity: load modes, hashes, key ranges, partitions, views, fencing tokens. The goal of this concept is therefore **half as many concepts**, with speed as a constraint and not as the aim.

## 1. PostgreSQL is the only target and the only place of coordination

**Decision.** The program loads into PostgreSQL only. Definitions, runs, locks and status live in the target database. There is no other state: no state file, no broker, no service that has to be reachable.

**Why.** Session locks, transactions and the system view `pg_locks` give locking, dead-run detection and counting without building anything.

**Price.** Other targets are out.

## 2. Compare in the target, by row comparison

**Decision.** Every run writes the complete source table into a staging table in the target. Postgres finds the differences with a join and `ROW(...) IS DISTINCT FROM ROW(...)`.

**Why.** No hash, no canonical text form of values, no type normalisation in the program. The comparison happens in the target types, where it is exact. The program stays a pipe.

**Price.** Every run writes the whole table once, even if nothing changed. At 10⁷ rows staging, diff and publishing add up to more than a minute.

**Rejected.**
- *Hash per row in the worker*. Faster for large tables, but brings the hash definition, its recomputation after type changes and key ranges for bounded memory.
- *A stored hash column in the mirror.* Would roughly halve the comparison on wide tables because only key and hash of the mirror are read. Kept in reserve for a concrete table that is too slow.
- *`EXCEPT`.* 40 times slower on a wide table.
- *Sorted merge of two ordered streams.* Needs identical sort order in source and target, which collations do not guarantee.

## 3. One flow instead of load modes

**Decision.** Initial load, follow-up load and tables without a key take the same path: staging, compare, apply in one transaction. There is no `append`, `scd1`, `scd2`, `replace` or `snapshot`.

**Why.** Every mode is a code path of its own with its own edge cases. One path can be tested completely.

**Price.** The initial load writes twice (staging table, then mirror). Tables without a key are deleted and re-inserted on every run, which bloats the table until autovacuum has cleaned up.

**Rejected.**
- *Swapping tables by renaming or attaching a partition.* Needs an exclusive lock that long-reading consumers block, and breaks dependent views.
- *`TRUNCATE` and reload.* Not safe under MVCC: a concurrent reader can see an empty table.
- *Views that switch to a published run number.* Only needed when several transactions write the same table in parallel, which this design does not do.

## 4. Mirror plus change log instead of a history table

> **Changed by decision 31.** The change log is on unless it is switched off.
>
> **Changed by decision 40.** The validity periods are a view over the change log, and its speed is measured (section 13 of `docs/measurements.md`).

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

**Why.** No naming scheme, no clean-up, no leftovers of dead runs: the tables disappear with the connection.

**Price.** Postgres does not scan TEMP tables in parallel workers. The gain measured with an unlogged staging table (40 s down to 26 s at 10⁷ rows on two cores) is lost. In the working range of up to 10⁶ rows this is irrelevant. Parallelism comes from loading several tables at once.

**Rejected.** *Unlogged staging tables with a fixed name.* This was the design until the write-up. It needs a second connection, names per run and a clean-up step for dead runs.

**To be revisited** if a single large table has to get faster.

## 7. The lock hangs on the connection, and publishing happens on that connection

**Decision.** A session-level advisory lock per target table, taken on the control connection. The publishing transaction runs on the same connection.

**Why.** If the process dies, connection, lock and open transaction are gone together. A zombie cannot commit, because a COMMIT needs a command from a client that no longer exists. This makes a fencing token unnecessary.

**Price.** The control connection must reach Postgres directly, not through a pooler in transaction mode. Advisory locks share one number space per database with every other application that uses them. During a long statement Postgres notices a dead client only with `client_connection_check_interval`. After a machine or network failure, release depends on TCP keepalive.

## 8. Every table on its own

**Decision.** Each table has its own lock, its own run and its own transaction.

**Why.** A broken table does not hold up the others. Parallelism and distribution over machines become simple. This was the user's correction of an earlier draft.

**Price.** Tables of one source are published at different moments. For a short time `orders` can be new while `customers` is old.

**Rejected.** *All tables of a source in one transaction.* Gives a consistent state across tables, but one failing table blocks all, the transaction gets long, and the work cannot be spread over workers. If cross-table consistency is ever needed, it would be an explicit group of a few tables, not the default.

## 9. One file per source with include and exclude

> **Changed by decision 21.** One file per source stays. Tables are named one by one, there are no patterns.

**Decision.** A source file holds the connection once, patterns for tables, and overrides for single tables.

**Why.** With 200 tables in an ERP system, one file per table means 200 near-identical files and soon a wish for defaults and inheritance.

**Price.** With a pattern like `dbo.*`, new tables in the source appear in the target automatically. A connector needs a second function that lists tables and keys.

**Rejected.** *One file per table*, the earlier draft.

## 10. Orders in Postgres, workers pull

> **Replaced by decision 20.** Workers still pull. There are no orders and no submitters any more.

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
- A connector becomes two Python functions. For REST interfaces that is the natural language.
- Informix needs the IBM ODBC driver on the machine in any language, so "one static binary" does not hold for that source anyway.

**Price.** Python and the drivers have to be present on every worker. A Rust binary would have had a fixed memory footprint and no runtime.

**Rejected.** *Rust core*, the starting idea. Also considered: a Rust core with connectors as subprocesses that write Arrow IPC to stdout. More moving parts for no measured gain.

## 13. A connector is two functions, reachable in three ways

> **Changed by decision 27.** One function, Arrow only, and no connector file in a repo. Entry points and optional extras stay.

**Decision.** `tables(cfg)` and `read(cfg, table)`. `read` may yield Arrow batches or lists of dicts. Connectors are found through Python entry points; the shipped ones use the same mechanism. Heavy dependencies are optional extras. A file in the jobs repo works without any packaging.

**Why.** Not everybody needs every connector. Writing one must be possible in a few lines.

**Price.** As soon as outside packages build on the two functions, they can no longer be changed freely. Types inferred from dicts can flip between runs.

**Rejected.** *A separate package per shipped connector from the start.* Five packages mean five releases and version alignment. The mechanism allows it later without a change for users.

## 14. Definitions in a Git repo, delivered by `git pull`

> **Replaced by decision 22.** The definition is still kept in Git. It reaches the workers through the target, not through a checkout.

**Decision.** Source files, custom connectors, the schedule and the pinned program version live in one repository. A load host has a checkout that is updated every few minutes.

**Why.** The scheduler only has to be able to start a command. Program version and source files are in the same commit. A deployment ends no process: a worker reads the source file only when it starts a table, so a new source never interrupts a running load. Only a new program version needs a restart, and that happens between two tables.

**Price.** After a change, workers run with different states for a few minutes. Drivers are installed by hand once per machine.

**Rejected.** *A container image as the unit of delivery.* The scheduler would have to pull and start images, which is not a given.

## 15. Source secrets are stored in the target, encrypted for the workers

> **Changed by decision 26.** The encryption and the key pair stay. Named secrets, the commands that set them and the fallback to environment variables on the worker are gone.

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

**Why.** A useful image needs the ODBC drivers of Microsoft and IBM, which are under vendor licences and do not belong into an MIT project.

## 17. Schema changes: additive automatically, everything else stops

**Decision.** A new column in the source is added to the target. A missing column or a changed type fails the run and leaves the target unchanged.

**Why.** Adding is safe. Everything else needs a person who decides what happens to existing data.

**Price.** Adding a column takes a short exclusive lock that a long-reading consumer can block. A `lock_timeout` turns that into a failed run.

## 18. Safety limits before publishing

> **Changed by decision 42.** The limit on zero rows applies only when the mirror exists and holds rows.

**Decision.** A run aborts if the source delivers zero rows or more than `max_delete_share` (default one half) of the rows would disappear.

**Why.** "Consistent" is not enough. A broken source would empty the mirror in a perfectly consistent transaction.

## 19. A worker claims only what it can load

> **Dropped by decision 27.** A worker takes any due table. What it cannot load fails with a reason.

**Decision.** Before claiming, a worker determines the sources for which it has the source file in its checkout and a secret it can decrypt. It passes this list to the claim, which hands out only runs of those sources.

**Why.** After a new source is merged, workers pull it at different moments. Without this rule, a worker that is behind would claim a table of the new source and fail it. With it, adding a source needs no restart and no coordination: each worker starts serving the source as soon as it has both parts.

It also allows workers that reach only some sources, for example one inside a separate network zone.

**Price.** If no worker has both parts, the runs wait without any error. The status view has to show waiting runs that no running worker offers to load.

**Evidence.** None yet. The claim function in experiment 5 has no such filter.

## Second round

The first round was designed from the hardest case: several workers, a scheduler on another machine, a web UI. Every question got another concept as its answer: orders, waiting runs, a run that lists tables, a rule for duplicates, a rule for precedence. The owner stopped this: if that much has to be explained, the design is wrong, and a reader of the repo should think "so that is how it can be done".

The second round therefore looked for ideas that make rules disappear instead of adding them.

## 20. A maximum age per table instead of orders

> **Changed by decision 36.** A table may name times of day as well.

**Decision.** The definition says how old each table may be (`max_age`). A worker loads whatever is older than allowed, starting with the table that misses its target the most. There are no orders, no queue and no submitters. `rowvioli run` loads what is due once, `rowvioli work` does not stop.

**Why.**
- A table is either fresh enough or not. Nothing can be submitted twice, so the rule against duplicates and the question which order a run belongs to are gone.
- A table to be loaded every five minutes next to tables loaded hourly is two lines in the definition. It overtakes the others by itself, because it becomes overdue faster.
- Single execution and server are the same loop. One ends, the other does not.
- Load on the source spreads over time instead of arriving on the hour.

**Price.** This reverses the statement of decision 10 that nothing in the program knows about time. A process has to run permanently, or cron starts `rowvioli run` every minute. "Load at six" could not be said until decision 36. "Load now" needs the request of decision 23.

**Rejected.**
- *Orders with waiting runs*, decision 10. A second order for a table that already waits needed either a mapping of orders to runs, an incomplete answer or a double load.
- *Runs written one by one, with a run that lists the tables of a source.* Simpler than orders, but a table submitted every five minutes queued up behind 200 hourly ones and needed a rule for precedence.
- *A stored flag "requested" on every table.* Removed the queue but kept the external scheduler.

The idea is not new. Snowflake does the same with `TARGET_LAG` for dynamic tables.

## 21. Tables are named in the definition

**Decision.** The definition lists every table with its key. Nothing scans a source while the system runs. `rowvioli list <source>` prints the tables and keys of a source in the format of the definition. It is a helper for people.

**Why.** Explicit is better than implicit here. The table in the target holds exactly what the definition holds, every change passes a review, and nothing arrives without somebody's doing. `apply` needs no access to any source. A worker has one job: transport.

**Price.** 200 names in a file for a large ERP system. New tables of the source do not arrive by themselves. This reverses the proposal of the first round to let `include = ["dbo.*"]` pick them up.

**Rejected.**
- *A worker resolves patterns on every load.* The table list would be known only after a scan.
- *A scan on its own schedule.* A second schedule, and tables that vanished fail until the next scan.
- *The scheduler scans.* Scanning needs the connector, a route to the source and the decrypted connection. Whoever scans is a load host.

Patterns can be added later as a second job of the worker without changing the model.

## 22. The definition lives in the target, workers are stateless

**Decision.** `rowvioli apply <directory>` writes the definition into the target: one row per source, one row per table. A worker brings its connectors, the address of the target and the private key, and nothing else. It has no checkout and no file that describes a source.

`apply` is idempotent, never touches what the workers experienced, treats the directory as the whole definition and runs in one transaction. What is no longer in the directory is disabled, never deleted.

**Why.** All workers see the same definition at the same moment. The minutes of different states from decision 14 are gone, and so are the checkout, the `git pull` and the question how a worker notices a new program version. A new program version is an ordinary restart of the service. The pipeline that deploys the definition needs access to the target and nothing else.

**Price.** Whoever can write to the definition tables in the target can change what is loaded. Before, only a merge request could. Write access to them should be limited to the role that runs `apply`.

**Rejected.** *A checkout on every load host*, decision 14.

## 23. Facts are stored, the due time is computed

> **Changed by decision 36.** The target also stores the load times (`at`) and their time zone (`timezone`) per table, as definition like `max_age`.

**Decision.** Per table the target stores `max_age`, `loaded_at`, `attempted_at`, `attempts` and `requested_at`. When a table is due is computed from them in a view on every query. Workers and people ask the same view. A load that should not wait is requested by setting `requested_at`.

**Why.** A due time is a derived value, and the concept avoids those elsewhere too: running tables are counted from held locks, not from a counter (decision 11). A changed `max_age` or a changed retry rule takes effect at once. `apply` needs no exception for it. A crashed worker has to write nothing: the attempt was counted when the table was claimed.

`requested_at` is a point in time that nobody ever resets. The formula compares it with the start of the last run, so there is no flag that a worker could clear while somebody sets it.

**Price.** The formula is SQL, not Python. Changing it changes the schema.

**Rejected.**
- *A stored column "due from"*, set by workers after success and failure and by people for "now". It needed an exception in `apply` for a shortened `max_age`.
- *"Load now" only as the command `rowvioli run <source>`*, without a column. Whoever wants a load now would need a machine with connectors, and a button in a web UI would be impossible.

## 24. Retry with a growing pause

**Decision.** After a run that did not succeed, the next one starts after one minute, then after 2, 4, 8 minutes and so on, never later than one `max_age`. A success resets the pause. Failed checks, broken sources and crashed workers are treated alike.

**Why.** A short network failure must not postpone a nightly table until the next night. A table that is broken for good must not hammer the source.

**Price.** A table that stays broken reads the source about ten times on the first day.

**Rejected.**
- *Counting `max_age` from the last attempt.* A nightly table would be retried the next night.
- *Three attempts for dead runs, none for failed ones*, the first round. Two rules where one is enough, and a failed table waited for the next order.

## 25. One process per run

**Decision.** A worker starts a process for every table it loads.

**Why.** A Python thread cannot be ended, so a hanging run could not end itself after `max_seconds`. A crashing driver would take all tables of the worker with it. With a process per run, process, run and control connection end together.

**Price.** 0.1 to 0.2 s per table to start Python, import the libraries and reach the claim, measured in the prototype. That matters only for hundreds of tiny tables per minute on one machine.

**Rejected.** *Threads.*

## 26. The connection is a block in the definition, encrypted as a whole

> **Changed by decision 32.** `apply` percent-encodes a value that lands in the user info of a URL.

**Decision.** A source has a `connection` block in the definition. Its values may contain `$NAME` placeholders. `apply` fills them in from its environment, encrypts the whole block with the public key and stores one ciphertext per source. The connector receives the decrypted block as a dict and defines its fields. There is one key pair for all workers of a target. The public key is a file next to the definition.

**Why.**
- Nobody builds a connection string by hand in an environment variable. The secret manager holds plain values such as a token or a password.
- The address of a source is visible in the definition and its review and still encrypted in the target. Someone who can only write to the target cannot point a password at another server.
- A source that needs more than one value, such as a URL and a token, needs no special case.
- A new password is a changed variable and one `apply`. `apply` encrypts everything anew every time, so no command for re-encrypting is needed.
- The word "secret" no longer fit: the block contains the address, which is not secret.

**Price.** The place where `apply` runs holds every secret in its environment. The ciphertext changes on every `apply` although its content is the same. A wrongly built connection shows only when a table is loaded, as a failure on its row. For test and production with different addresses, the address has to be a placeholder too and is then no longer visible in the file.

**Rejected.**
- *Named secrets set with `rowvioli secret set`*, decision 15. Whoever sets them has to know the format the connector expects.
- *The address in the definition in clear, only the password encrypted.* Visible and reviewable, but a writer to the target could redirect a password.
- *Environment variables on the workers.* Every worker would have to know every password and restart for a new source.

## 27. A connector is one function and trusted code

**Decision.**

```python
def read(connection: dict, table: str, options: dict) -> Iterator[pyarrow.RecordBatch]:
```

Nothing else goes in or out. A connector may offer `tables(connection)` for `rowvioli list`. A worker never calls it. Connectors are installed on the workers by the operator, as an optional extra of the core package or as a package of their own. A worker takes any due table. If its connector is missing or the connection cannot be decrypted, the run fails with a reason that names the worker.

**Why.**
- All data enters through one fixed interface. The connector sees no target, no lock and no other table.
- A rule that connectors must take the address from the connection only could not be enforced: a connector's code can fetch credentials from anywhere. It is therefore not a rule but a promise for the shipped connectors. Everything else is code the operator trusts.
- Lists of dicts with guessed types were a known weak spot, because guessed types can flip between two runs. With Arrow only, the connector names its schema.
- The key is in the definition, so a worker needs no second function to ask the source for it.
- Without the filter of decision 19, a run never waits silently for a worker that could load it.

**Price.** All workers on one target have to be equipped alike. A worker that reaches only some sources, for example in a separate network zone, would take runs it cannot load. When rolling out, the connector has to be installed on every worker before the source is applied. A connector that reads JSON needs two more lines to name its schema.

**Rejected.**
- *The claim filter*, decision 19.
- *A connector as a file in the repo of the definition*, `type = "python"`. The worker has no checkout. Code stored in the target would give everybody with write access to it code execution on the workers.

If network zones are needed later, `rowvioli work --sources erp,crm` is the smallest way there.

## 28. ADBC alone carries the control connection

**Decision.** The core uses the ADBC driver for PostgreSQL for everything on the control connection. There is no second Postgres driver.

**Why.** Lock, TEMP tables and transaction have to be on the same connection, so two drivers side by side are not possible: it is one or the other. Experiment 8 played a complete run through ADBC: the session lock survives COMMIT and ROLLBACK and ends with the connection, the staging table is a TEMP table on that connection, the driver streams, nothing is visible before COMMIT, and errors arrive with their SQLSTATE.

**Price.** The driver wraps every query that returns rows into `COPY`. `SHOW` fails because of that and has to be written as `current_setting(...)`. The driver decides the column types of the staging table, and the mirror inherits them. The prototype named the losses: `varchar(n)` becomes `text` and `numeric(p,s)` becomes `numeric`, so the schema check cannot see a change between such types, and an unconstrained `numeric` beyond 38 digits fails the run. The driver also decides the chunk size, about 16 MB, and with it the memory of a run. These are stated, not fought.

**Rejected.**
- *psycopg 3, row by row.* Passes every row through Python objects and takes eight times as long to fill the staging table.
- *psycopg 3 with pgpq.* As fast as ADBC, but two more dependencies and a type table of our own.

**Evidence.** Experiment 8.

## 29. A total limit, counted from held locks

**Decision.** `max_running` in `_rowvioli.meta` limits the number of tables loading at the same time in a target. When claiming, Postgres counts all held table locks. If the number is reached, nobody gets another one.

**Why.** Until now nothing limited the target: every additional worker added connections. This is the mechanism of `parallel`, counted once over everything, so both limits rest on one mechanism.

**Price.** One counting lock for the whole target instead of one per source. It limits loading tables, not connections: there is one more connection per worker.

**Rejected.** *A connection limit on the database role of the workers.* No code, but a second mechanism and an error path for refused connections.

**Evidence.** The prototype: six workers never exceeded `parallel` or `max_running`, and with the counting lock replaced by `SELECT 1` the total broke in 1 of 4 runs (`docs/measurements.md`, section 9). Experiment 5 counted per source only.

## 30. The target is exactly one database

**Decision.** Mirrors and bookkeeping are in the same database. A worker brings the address of that database. The address may name several nodes of a cluster.

**Why.** Publishing writes the mirror and the bookkeeping in one transaction.

**Price.** Several target databases need their own workers and their own definition each.

**Evidence.** None for an address with several nodes through ADBC.

## 31. Smaller decisions of the second round

> **Changed by decision 34.** A worker asks whether something is claimable, not whether something is due.

Decided by the owner on the proposals in `docs/open-points.md`:

- **The change log is on by default.** Every table with a key gets one unless the definition says `log = false`. The first round proposed the opposite. The price: every mirror has a second table that only ever grows, and nothing prunes it.
- **A table is stopped through `apply` only.** It is loaded and retried until it is removed from the definition and `apply` disables it. Terminating a run's connection ends that run and nothing more.
- **`rowvioli apply --check`** reads and checks a definition without writing anything. It runs locally and needs no target.
- **`work` is part of the first version.** It is the loop of `run` without the end.
- **A worker asks every two seconds** whether something is due. No `LISTEN`/`NOTIFY`.
- **Tables of a source are published independently.** Decision 8 stays as it is.
- **`max_age` is required** at source level.
- **A changed key stops the run.** If the key in the definition differs from the primary key of the mirror, the run fails and says so. A person drops or renames the old mirror, and the next run builds it anew. This follows decision 17: only additions happen automatically.
- **Progress is computed, not written.** The status view finds the holder of the table lock in `pg_locks` and its rows so far in `pg_stat_progress_copy`. The row count of the last run serves as the expected number. This is the pattern of decisions 11 and 23. It covers filling the staging table, not the steps after it.
- **The program creates no database roles.** The README lists the rights each party needs. The operator sets them up.

## Changes of the second round

| Point | First round | Now |
|---|---|---|
| When a table is loaded | when somebody creates an order | when it is older than its `max_age`, or requested |
| Who decides the time | an external scheduler | nobody. The definition states the freshness. |
| Which tables | patterns, resolved by a worker for every order | named in the definition |
| Where a worker finds the definition | checkout of a jobs repo, updated by `git pull` | in the target, written by `apply` |
| Unit of work | order, then one waiting run per table | the table itself |
| Retry | dead runs up to the third attempt, failed runs not at all | every unsuccessful run, after a growing pause |
| Slot | a thread | a process |
| Secrets | named, set one by one, a table of their own | part of the connection block, filled in by `apply` |
| Connector contract | `tables` and `read`, Arrow batches or lists of dicts | `read`, Arrow batches |
| Key | primary key of the source unless overridden | named in the definition |
| A worker that cannot load a table | does not claim it | takes it and fails with a reason |
| Limits | per source, per worker | per source, per worker, per target |
| Driver of the control connection | open | ADBC alone |
| Commands | `init`, `check`, `submit`, `work`, `run`, `key new`, `secret set`, `secret rekey` | `init`, `key new`, `list`, `apply`, `work`, `run` |

## Third round: after the prototype

On 2026-11-12 a throwaway prototype tried out the model of the second round as a whole (`.scratch/prototype/findings.md`). The model held: facts in one row, everything else computed, the connection as the lock. It strained only at the edges: the driver, the boundary between a worker and its run processes, and the first screen of the README. None of it called for a new concept. Four points needed a decision, and the owner took the smaller option each time. Everything else is a correction, listed at the end of this round.

## 32. `apply` percent-encodes a secret in the user info of a URL

**Decision.** If a placeholder value lands in the user-info part of a URL (`scheme://user:pass@host`), `apply` percent-encodes it before encrypting. Removing the connection's values from error texts stays as well.

**Why.** A driver quotes not only whole values but also the part of a URL it cannot parse. With the password `p@ss%word` unencoded, libpq reported `invalid percent-encoded token: "ss%word@127.0.0.1"`: part of the password, unscrubbed, in the status, in `runs` and on stdout. Encoded, the password is never misparsed, so there is no fragment to quote. Authors keep writing plain values and never encode by hand.

**Price.** `apply` has to recognise a URL in a connection value. A value encoded by hand is encoded twice and fails to log in. Scrubbing stays best effort for other formats.

**Rejected.**
- *Sealing the raw placeholder values as well and scrubbing every part of them.* More to carry and to match, for the one case that encoding already removes.
- *Only telling authors to encode.* Leaves the leak to whoever does not read the README.

## 33. `work` stops by letting its runs finish

**Decision.** On SIGTERM (on Windows Ctrl+Break, SIGBREAK, since SIGTERM is never delivered there) `work` starts nothing new, waits for its running runs, each still bounded by `max_seconds`, and exits. Killing it hard kills its runs too. They count as `worker lost` and are retried after the pause.

**Why.** In the prototype, killing `work` left its run processes behind as orphans that nobody ended after `max_seconds`. The README promised that a new program version lets running loads finish. Waiting is the smallest way to keep that promise, and a hard kill falls back on the path that already handles every crash.

**Price.** A restart can take up to `max_seconds`. The service manager has to allow that, for example `TimeoutStopSec` with systemd, or it kills hard.

**Rejected.** *Ending the runs at once on SIGTERM.* Throws away loads that would have finished, for nothing a hard kill does not already give.

## 34. A worker asks what is claimable, not what is due

**Decision.** A worker starts a run process only if something is claimable: due, and within `parallel` and `max_running`. It asks the same view with the same two counts as the claim.

**Why.** With the limits full, every worker still started up to `--slots` processes every two seconds that found nothing to claim, about 0.18 s each. Asking the claim's question removes those processes.

**Price.** The question repeats the counts of the claim. It is not exact: between question and claim another worker can take the last place, and the process finds nothing. That is harmless.

## 35. `apply` fails when two sources share a `target_schema`

> **Replaced by decision 39.** The rule that a schema belongs to one source is gone; the definition gives no target name twice.

**Decision.** `apply` fails if two sources have the same `target_schema`, as it fails if two tables of a source get the same target table.

**Why.** The README said that a schema belongs to exactly one source, but nothing checked it, so the mirrors of two sources could collide. One check in `apply` turns the rule into a fact.

**Price.** Two sources cannot share a schema even when their table names would never collide.

## Fourth round: load times

On 2026-11-12 the owner asked for tables that are loaded at a fixed time of day (`.scratch/load-times/spec.md`).

## 36. A load time is a request the clock makes

**Decision.** A table may name times of day (`at`) in a time zone (`timezone`). It is due at its next load time after the last run began, or by its maximum age, whichever comes first. The times are part of the definition. The due time is still computed from stored facts on every query.

**Why.** The owner needs tables that are loaded at a fixed time. A daily maximum age wanders, and a cron that sets `requested_at` keeps the time outside the definition and does not catch up. The rule is the request's rule with the clock as the one who asks, so it brings no new concept: no schedule, no stored next time, nothing to reset, no process that knows about time beyond the view.

**Price.** The sentence "you state the freshness, not the time" is no longer the whole truth: you may state both. The target needs to know time zones, and a wrong zone on a row breaks the view. Load on the source arrives at the named minute again for the tables that use it, which decision 20 had spread out. `parallel` and `max_running` still bound it.

**Rejected.**
- *A cron outside that sets `requested_at`.* Works today and stays the right answer for "load when the source's batch is done". For a time of day it keeps the time out of the definition and loses a missed run.
- *Aligning `max_age` to a grid* ("daily, anchored at 14:00"). A second meaning for the one setting everybody knows, and it cannot say 06:00 and 14:00.
- *Cron syntax or weekdays.* A schedule language where a list of times answers what was asked.
- *A default time zone.* 14:00 that silently means UTC is a mistake found in production.

## Fifth round: visibility

On 2026-11-12 the owner asked to see what a worker does (`.scratch/visibility/spec.md`).

## 37. A worker says what it does, and nothing keeps it

**Decision.** `work` writes one line per event to stderr: start, a run's start and end, a failure, an unreachable target, stopping. `run` writes the start and end lines of its runs, not the worker's start line. Each begins with local date and time, and there is no setting for them. The lines are not stored. `rowvioli status` prints the status view as a table; the target stays the truth. At a terminal `work` first shows its mascot once; when stderr is not a terminal there are only the lines.

**Why.** The target already holds everything (`status`, `runs`), but looking needed `psql`, and a worker that waits looked the same as one that hangs. The loop already hears each run's claim and answer, so the lines cost nothing new, and the log system the operator has (journald, Docker) is the right place for them. A second record would have to agree with `runs`.

**Price.** The lines are only as durable as the operator's log system, and a worker says only what it does itself; what the others do is in the status view. Run processes still say nothing, because a driver message may quote a connection value (decision 32).

**Rejected.**
- *A log table in the target.* `runs` is that.
- *Python's `logging` with levels and handlers.* Nothing to configure is the point.
- *JSON lines.* The structured data is in the target.
- *Progress lines during a run.* The status view has the progress; a worker writes nothing for it.
- *A waiting line* ("nothing due, next: ... at ..."). It needed the only extra query, and it is state of the target, not something the worker does; a line from two hours ago does not prove the worker lives, and it repeats with two workers. `rowvioli status` (column `due`) answers it for every table.

## Sixth round: connectors

On 2026-11-12 the owner asked how more connectors can be built without violating a licence (`.scratch/connectors/spec.md`).

## 38. rowvioli ships only code written for it and permissive dependencies

**Decision.** rowvioli ships only code written for it and dependencies under a permissive licence; everything under another licence is installed by the operator or lives in a separate package. Four consequences:

1. A connector's code is written from the public documentation of the source. Nothing is copied or ported from another project's connector, whatever tool does the porting.
2. A dependency of the core or of an extra is under MIT, BSD or Apache-2.0. It has a row in the dependency table of `docs/package.md`; a test fails when it has none.
3. Vendor drivers, SDKs and specification files are in no package, no repo file and no image. The operator installs them (extends decision 16 from the image to everything). Product names appear as plain words only, no logo.
4. A connector that cannot keep 1 to 3 is a separate package with its own licence, outside this repo, registered through the entry point group `rowvioli.connectors` (decision 27).

**Why.** Before this, the rule was spread over decision 16 and one table. Whoever added the fifth connector had nothing to follow and nothing that stopped a mistake. One sentence judges every later connector the same way.

**Price.** Sources whose only library is GPL or a vendor SDK are not in the core. They need a package of their own, and someone to maintain it.

**Rejected.**
- *Bundling drivers for convenience.* It redistributes the vendor's files.
- *A GPL library behind an optional extra.* Whether the MIT code stays untouched by it is disputed. A separate package ends the dispute.
- *A licence scanner as a CI service.* One small test over the table is enough. It checks that the row exists, not what the licence is: the row is written by a person who looked.
- *A contributor licence agreement.*

This is the project's rule, not legal advice. A connector for a source whose SDK is under a vendor licence is looked at by a lawyer before it is published, even as a separate package.

## Seventh round: target names and history

On 2026-11-13 the owner asked for ways to set the name and the schema of a table in the target, and for a table as it was at a moment (`.scratch/target-names-and-history/spec.md`).

## 39. A table says where it lives, and the definition gives no target name twice

**Decision.** `target_schema` stands at the source as the default and may stand at a table. `target_table` stands at a table only. A table takes three names in its schema: its own, `<name>__log` and `<name>__history`. `apply` and `list` fail when two tables of the definition, of whichever sources, take the same one, name both and name `target_table` as the way out. This replaces decision 35: the rule that a schema belongs to one source was a means, the rule that no two tables load into one mirror is the point. A target table may have 54 bytes (63 minus `__history`), a schema 63; neither may be empty, and the schema is not `_rowvioli`. Only the definition owns names: a table that left it holds no name. A changed name moves nothing, and `apply` says one line for it.

**Why.** Two tables of one source with the same last name part could not both be loaded, a source could not spread over schemas and two sources could not share one, though no mirror would have collided. Checking names instead of schemas allows all three and still stops the one real danger. A table that left the definition is disabled and holds nothing: a user who renames a table in the source expects one edit in the definition, and a name that stayed taken would have asked for a hand-deleted row in the bookkeeping, for which no command exists. If another table takes the name over, the checks before publishing decide on the first run. The line of `apply` is there because the alternative is a stale table under the old name that consumers keep reading without a failure.

**Price.** A changed name leaves the old tables where they are, and a person renames or drops them (README, "What a person does by hand"). One number, 54, now holds for every table, though only a table with a log needs the room.

**Rejected.**
- *A fixed layout* such as one `staging` schema, a prefix or a name pattern. The two settings express each of them.
- *`apply` renaming or dropping.* The program never does, as with a changed key.
- *Names that stay taken by tables the definition no longer has.* Needs a command for something the definition should say.
- *Keeping the check for schemas next to the new one.* It would forbid what the new rule allows.

## 40. A change log says when, is complete or absent, and history is a view

**Decision.** Every row of a change log carries `_loaded_at`, the `now()` of the publishing transaction, the same value as `tables.loaded_at`. A change log that exists is complete: a log that is created begins with every row of the mirror as `I`, and a run that would publish without writing to a log that exists, or build a new mirror beside it, fails and names the log. The view `<target table>__history` reads nothing but the log: `_valid_from` is a row's `_loaded_at`, `_valid_to` that of the next row with the same key, ordered by `_loaded_at`, rows with `D` left out afterwards; an open period is null. The table at a moment is one condition on the view. A run creates the view when it is missing and replaces it when the log got a column, and touches it never otherwise. No index is built.

**Why.** The time was in `_rowvioli.runs`, which is bookkeeping, may be cleaned up and needs rights on `_rowvioli`; with it in the log, the history needs nothing in `_rowvioli`. The view is a plain view, so the right to read the view is enough: the reader needs no right on the log and none in `_rowvioli`. A history that is silently wrong is worse than none: a log switched on late misses every unchanged row, one switched off shows outdated versions as current. Failing is the project's own answer, and a changed key already asks for a person. The view orders by `_loaded_at` and not by `_run` because run numbers start again when `_rowvioli` is built anew. Null for an open period is what readers of validity columns know, where drivers and BI tools disagree about `infinity`. A plain view lets a consumer read history with one right and takes no lock in an ordinary run. The measurement (section 13) shows what it costs: fast for one key with an index a person may create, as slow as the whole view for one moment, where the same moment asked of the log directly is 2.6 times faster. The README names both as advice.

**Price.** A table whose log is dropped or renamed needs a person to drop or rename the view with it. The view for a moment reads the whole log. A clock set back between two runs of one table would put their rows in the wrong order. A target built before this decision has no `_loaded_at`, and nothing converts it (schema version 3, nothing was published).

**Rejected.**
- *The time from `runs`.* The bookkeeping is not for readers.
- *A function `as_of(table, time)` in place of the view,* or a second view per moment. The condition is one line and works for two tables at the same moment.
- *A history table kept by the run.* Decision 4 stands: the log is a by-product of the diff.
- *`infinity` for an open period.*
- *A log that may have gaps,* with a note that it does.
- *An index built by the run.* It costs every insert, and no index helps the query for a moment.

## Eighth round: after the shakedown

## 41. Options narrow a connection and never move it

**Decision.** The connection says where a source is. An option of a table, which sits in plain text in the target, may only say where to read inside that source. A REST `path` is a path on the connection's host: it starts with `/`, and the joined address keeps scheme, host and port. A `file` table is a file inside the connection's `path`; `..` and an absolute name fail. The connector checks it at every run, `apply` repeats the `/` rule for `rest` so that the author learns it first.

**Why.** Decision 26 encrypts the connection as a whole, the address too, so that whoever can write to the target cannot point a password at another server. An option that is joined to the address undid it: `path = ".evil.com/x"` sent the token to a host of someone else's choosing, and a `file` table `../outside.csv` read any file the worker can read. The check belongs in the connector because a writer of the target does not pass `apply`.

**Price.** A REST API whose pages live on another host needs a connector of its own. A `file` source cannot read through a symbolic link that leaves its directory.

**Rejected.**
- *Checking only in `apply`.* A writer of the target bypasses it.
- *Putting `path` into the encrypted connection.* Then one connection per endpoint, and the tables of a source could not differ.
- *Hiding the URL in the reason.* The reason names the option, so that no address lands in a log.

## 42. Zero rows protects a mirror

**Decision.** The limit of decision 18 on zero rows applies only when the mirror exists and holds rows. A first load, or a mirror that is empty, publishes zero rows. `max_delete_share` is untouched.

**Why.** The limit is there so that a broken source cannot empty a mirror in a consistent transaction. A mirror with nothing in it has nothing to protect, and a new source table that is still empty would otherwise wait, failed, for its first row, with a table that does not exist for the consumers who build on it.

**Price.** A source that is broken from its first run and delivers nothing looks like an empty table. Nothing was there to lose.

**Rejected.**
- *A switch per table for allowing empty loads.* A concept for a case that has a plain answer.
- *Keeping the limit for first loads.* It forbids mirroring an empty table and its columns.

## 43. `max_seconds` is the one bound of a run

**Decision.** A run is bounded by `max_seconds` and by nothing else. No connector sets a timeout of its own; the REST connector sent every request with five seconds before.

**Why.** A hidden limit in one connector is the one bound a person does not find in the definition. A slow API failed at five seconds although the table allowed an hour, and the same table loaded from a file or a database never met such a limit. One bound that is visible, per source or table, is enough, and the worker ends the run's process when it is over.

**Price.** A source that never answers holds its run until `max_seconds`, and that table's slot with it.

**Rejected.**
- *A timeout option for `rest`.* A second bound beside the first.
- *A longer fixed timeout.* It moves the problem.

## Corrections after the prototype

| Point | Before | Now |
|---|---|---|
| Decision 25, price | about half a second per table | 0.1 to 0.2 s per table |
| Decision 28, price | the driver decides the column types | the losses are named: `varchar(n)` to `text`, `numeric(p,s)` to `numeric`, no unconstrained `numeric` beyond 38 digits, chunks of about 16 MB |
| Decision 29, evidence | none | the prototype, with and without the counting lock |
| First screen of the README | `apply` and `work` | also `init`, `key new` and the two environment variables |
| Status view | one column `status` with `loading (worker etl-02)` and `failed: <reason>`, a column `table` | `status` and `reason` separate, `source_table`, no worker |
| `dead` | a stored run status | computed: a `running` row without its lock. Its table shows as `failed` with the reason `worker lost` |
| Answer of `run` | `"step": "check"` for a failed table | `status` and `reason`. The reason already says what failed |
| `run <source> <table>` with an unknown or disabled name | not covered | fails |
| `apply` on a target without `init` | not covered | says: run `rowvioli init` first |
| A missing `ROWVIOLI_TARGET_URL` or `ROWVIOLI_KEY_FILE` | not covered | `run` and `work` name it at start |
| Request while loading, and the run fails | not covered | one more run at once, then the pause |
| Share of deletions | checked in step 4 | checked after the diff, still before publishing |
| Chunk | a few thousand rows | the size the connector delivers, about 16 MB with ADBC |
| One file per source | a rule | a convention |

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
