# Decisions

Every decision of the concept with its reason, its price and what was rejected. The order follows the discussion of 2026-11-11, so the document also shows how the design got to where it is.

There were two rounds on that day. Decisions 1 to 19 are the first round. The second round (decisions 20 to 30) replaced the model of orders, a jobs repo and an external scheduler with a maximum age per table, definitions in the target and stateless workers. Decisions of the first round that no longer hold are marked and kept, with their text unchanged. A third round (decisions 32 to 35) followed on 2026-11-12, after a throwaway prototype had tried out the model of the second round. A fourth round (decision 36) added load times, a fifth (decision 37) the lines of a worker, a sixth (decision 38) the rule for licences, a seventh (decisions 39 and 40) target names and history. An eighth (decisions 41 to 43) followed on 2026-11-15, after the shakedown of the built wheel, a ninth (decisions 44 to 46) on 2026-11-17, after the first mirror out of the box, and a tenth (decisions 47 to 49) on 2026-11-17, after the shakedown of the second wave. An eleventh (decisions 54 and 55) followed on 2026-11-24, after the design of schema changes and its shakedown.

Evidence refers to `docs/measurements.md`.

## Starting point

The first idea was a very fast Rust program. The discussion showed that speed was not the problem. The problem was complexity: load modes, hashes, key ranges, partitions, views, fencing tokens. The goal of this concept is therefore **half as many concepts**, with speed as a constraint and not as the aim.

## 1. PostgreSQL is the only target and the only place of coordination

**Decision.** The program loads into PostgreSQL only. Definitions, runs, locks and status live in the target database. There is no other state: no state file, no broker, no service that has to be reachable.

**Why.** Session locks, transactions and the system view `pg_locks` give locking, dead-run detection and counting without building anything.

**Price.** Other targets are out.

## 2. Compare in the target, by row comparison

> **Changed by decision 55.** The comparison and publishing read and write the rows of the mirror alone (`ONLY`), never those of a table that inherits from it.

**Decision.** Every run writes the complete source table into a staging table in the target. Postgres finds the differences with a join and `ROW(...) IS DISTINCT FROM ROW(...)`.

**Why.** No hash, no canonical text form of values, no type normalisation in the program. The comparison happens in the target types, where it is exact. The program stays a pipe.

**Price.** Every run writes the whole table once, even if nothing changed. At 10⁷ rows staging, diff and publishing add up to more than a minute.

**Rejected.**
- *Hash per row in the worker*. It brings the hash definition, its recomputation after type changes and key ranges for bounded memory.
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

> **Changed by decision 54.** The mirror follows the source wherever a change log keeps what was: a column that goes, a type, a key and a rename are carried out by the run. What still stops is what a person must decide, and what a consumer built on.

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

`apply` is idempotent, never touches what the workers experienced (one exception, decision 46), treats the directory as the whole definition and runs in one transaction. What is no longer in the directory is disabled, never deleted.

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

Nothing else goes in or out. A connector may offer `tables(connection)` for `rowvioli list`. The worker process never calls it (decision 50: a person on a worker's machine does). Connectors are installed on the workers by the operator, as an optional extra of the core package or as a package of their own. A worker takes any due table. If its connector is missing or the connection cannot be decrypted, the run fails with a reason that names the worker.

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

**Price.** The driver wraps every query that returns rows into `COPY`. `SHOW` fails because of that and has to be written as `current_setting(...)`. The driver decides the column types of the staging table, and the mirror inherits them. The prototype named the losses: `varchar(n)` becomes `text` and `numeric(p,s)` becomes `numeric`, so the schema check cannot see a change between such types, and an unconstrained `numeric` beyond 38 digits fails the run. Decision 49 gives `numeric(p,s)` back up to 38 digits. The driver also decides the chunk size, about 16 MB, and with it the memory of a run. These are stated, not fought.

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

> **Changed by decision 54.** A changed key no longer stops the run: the mirror is replaced as a whole under the new key and the change log keeps its history. A key taken away still stops while a change log exists.

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
- **The program creates no database roles.** `docs/operation.md` ("The target") lists the rights each party needs. The operator sets them up.

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

> **Changed by decision 52.** Every line carries a mark (or a space), is coloured unless that is switched off, wherever it goes, and a run's line has columns.

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

**Decision.** `target_schema` stands at the source as the default and may stand at a table. `target_table` stands at a table only. A table takes three names in its schema: its own, `<name>__log` and `<name>__history`. `apply` and `list` fail when two tables of the definition, of whichever sources, take the same one, name both and name `target_table` as the way out. This replaces decision 35: the rule that a schema belongs to one source was a means, the rule that no two tables load into one mirror is the point. A target table may have 54 bytes (63 minus `__history`), a schema 63; neither may be empty, and the schema is not `_rowvioli`. No name of the definition (source name, source table, `key` column, `target_schema`, `target_table`) holds a control character (C0, DEL, C1, U+2028, U+2029): `apply` and `list` fail and show it as an escape (`\x1b`), since such a name can clear a terminal or forge a log line and is nothing a person types in SQL; a name already in a target keeps loading, and the lines write it with `?` (decision 52), until the definition is applied again, which `apply` refuses until the name is changed. Only the definition owns names: a table that left it holds no name. A changed name moves nothing, and `apply` says one line for it.

**Why.** Two tables of one source with the same last name part could not both be loaded, a source could not spread over schemas and two sources could not share one, though no mirror would have collided. Checking names instead of schemas allows all three and still stops the one real danger. A table that left the definition is disabled and holds nothing: a user who renames a table in the source expects one edit in the definition, and a name that stayed taken would have asked for a hand-deleted row in the bookkeeping, for which no command exists. If another table takes the name over, the checks before publishing decide on the first run. The line of `apply` is there because the alternative is a stale table under the old name that consumers keep reading without a failure.

**Price.** A changed name leaves the old tables where they are, and a person renames or drops them (`docs/loading.md`, "What a person does by hand"). One number, 54, now holds for every table, though only a table with a log needs the room.

**Rejected.**
- *A fixed layout* such as one `staging` schema, a prefix or a name pattern. The two settings express each of them.
- *`apply` renaming or dropping.* The program never does, as with a changed key.
- *Names that stay taken by tables the definition no longer has.* Needs a command for something the definition should say.
- *Keeping the check for schemas next to the new one.* It would forbid what the new rule allows.

## 40. A change log says when, is complete or absent, and history is a view

> **Changed by decision 54.** A change log is complete from its last change of key: replaying it from there gives the mirror. The history view has one branch per key, and a run drops it and creates it again whenever it carries out more than the adding of columns.

**Decision.** Every row of a change log carries `_loaded_at`, the `now()` of the publishing transaction, the same value as `tables.loaded_at`. A change log that exists is complete: a log that is created begins with every row of the mirror as `I`, and a run that would publish without writing to a log that exists, or build a new mirror beside it, fails and names the log. The view `<target table>__history` reads nothing but the log: `_valid_from` is a row's `_loaded_at`, `_valid_to` that of the next row with the same key, ordered by `_loaded_at`, rows with `D` left out afterwards; an open period is null. The table at a moment is one condition on the view. A run creates the view when it is missing and replaces it when the log got a column, and touches it never otherwise. No index is built.

**Why.** The time was in `_rowvioli.runs`, which is bookkeeping, may be cleaned up and needs rights on `_rowvioli`; with it in the log, the history needs nothing in `_rowvioli`. The view is a plain view, so the right to read the view is enough: the reader needs no right on the log and none in `_rowvioli`. A history that is silently wrong is worse than none: a log switched on late misses every unchanged row, one switched off shows outdated versions as current. Failing is the project's own answer, and a changed key already asks for a person. The view orders by `_loaded_at` and not by `_run` because run numbers start again when `_rowvioli` is built anew. Null for an open period is what readers of validity columns know, where drivers and BI tools disagree about `infinity`. A plain view lets a consumer read history with one right and takes no lock in an ordinary run. The measurement (section 13) shows what it costs: fast for one key with an index a person may create, as slow as the whole view for one moment, where the same moment asked of the log directly is 2.6 times faster. `docs/target.md` names both as advice.

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

**Price.** A REST API whose pages live on another host needs a connector of its own. A `file` source cannot read through a symbolic link that leaves its directory, also not as a match of a pattern.

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

## 44. Names that are always the same are defaults

**Decision.** `ROWVIOLI_KEY_FILE` unset means `worker.key` in the current directory, and `apply` without a directory takes `sources`, as `list` does. `run` and `work` stop at the start when the key file does not exist: they open it, and when that fails they name its path and the reason, and for a missing file say to copy `worker.key` from where `rowvioli key new` was run (only for a new target does `key new` create it); no table is attempted. The first mirror then needs one variable, `ROWVIOLI_TARGET_URL`.

**Why.** `key new` writes `worker.key` into the current directory and the definition lives in `sources/` by convention, so the first mirror said both names twice, and the slip that mattered, a run without the key, showed only per table as a failed decryption that named no next step. The first wording sent a second machine to `key new`, which creates a pair that decrypts nothing; the message now says to copy the key, and the reason of a wrong key (`holds no private key <id>`) names both ways out.

**Price.** A worker whose working directory is not where its key is (a service, cron) must still set `ROWVIOLI_KEY_FILE` or its working directory. A relative default depends on where the command runs.

**Rejected.**
- *`apply --init` creating the key pair.* The owner refused it: a private key must not appear as a side effect where the definition is deployed. That place holds every secret of the sources already, and a second private key there that nobody asked for is a copy to lose or leak. `key new` stays a command of its own, and `apply` without `worker.pub` says that `key new` creates it.

## 45. A near miss of a built-in type fails apply

**Decision.** A source `type` that is one edit (a letter added, left out, changed, or two neighbours swapped) from `postgres`, `file`, `odbc` or `rest`, or is `postgresql`, fails `apply` and `apply --check` with `type fiel is not installed here; did you mean file?`, unless a connector of that type is installed where `apply` runs: then it passes, and the message says so. `postgis`, two edits from `postgres`, and any other type pass. `apply` still works where no connector is installed.

**Why.** Decision 22 leaves the connectors to the workers, so `apply` does not know which are installed, and a mistyped `type` showed at the first run, per table. The four built-in names are the only ones `apply` can know, and a slip on one of them is far likelier than a connector of someone else that happens to be that close. Asking the entry points of the machine that applies costs nothing and gives a connector of one's own named `jdbc` a way through.

**Price.** A connector of one's own one edit from a built-in name fails `apply` on a machine that does not have it installed, such as a pipeline runner. An installed connector is otherwise not checked: `weather` passes whether or not a worker has it.

**Rejected.**
- *Refusing every type `apply` does not know.* The deployment needs no driver (decision 22).
- *Two edits from `postgres`.* `postgis` is a name of its own, and the slip it would catch is rare.

## 46. A changed target name makes a table new again

> **Changed by decision 53.** A table that is loading under the old name no longer finishes into the old mirror: its run fails and publishes nothing.

**Decision.** `apply` resets `attempted_at`, `attempts`, `reason` and `loaded_at` of a table whose target schema or table changes. The table is `new` again: status shows no age and no old reason, it is due at the next run, and a first failure pauses one minute. `requested_at` stays. These are the only facts a worker wrote that `apply` touches. A table that is loading under the old name finishes into the old mirror, sets `loaded_at` and `attempts`, but not `attempted_at`: it stays new, and the next run loads the new name.

**Why.** Under the new name no mirror exists yet, and the table kept its age, its attempts and its reason: a table last loaded under the old name sat out its `max_age` while `run` printed `{"tables": {}}`, and status described a mirror that does not exist.

**Price.** `apply` moves a load time forward for a rename and forgets how often the table failed. The old tables stay where they are (decision 39), and the first run under the new name loads everything again, as a new table does.

**Rejected.**
- *Leaving the table alone and asking the person to request a load.* Nothing says so, and the first load under a new name is not a request but a first load.

## 47. A connector refuses an option it does not know

**Decision.** `postgres`, `odbc` and `rest` fail the run when a table has an option they do not read, with `<table>: the option <name> is not one of the <type> connector's; it knows <options>` (`it knows no option` for `postgres` and `odbc`). `file` already did, since its options are DuckDB's. A connector of one's own decides for itself; the guide says that it should do the same. The `path` of a `file` connection stays readable in reasons, since a directory is no secret and a reason without it is no use; every other value of a connection, and a password inside a URL in any value, is scrubbed as before.

**Why.** `incremental = "updated"` or `query = "select ..."` on a `postgres` table loaded the whole table without a word, and a misspelt option of `rest` was ignored. A setting that does nothing looks like one that works.

**Price.** A definition that carried a stray option runs again only without it. `apply` does not know the options of a connector (decision 22), so the failure shows at the run.

**Rejected.**
- *Refusing in `apply`.* It does not know the connectors.
- *Ignoring with a warning.* A warning on stderr of a worker is not read.

## 48. Zero rows publish where every row may be deleted

**Decision.** Refines decision 42: zero rows fail a mirror that has rows unless the table's `max_delete_share` is 1.0. Who allows every row to be deleted allows an empty table, so no setting is added. Without a key the table is replaced as a whole and has no change log; its mirror counts as empty when it has no rows, as with a key. The reason says `max_delete_share = 1.0` allows an empty table.

**Why.** A source that really was emptied could not be mirrored, short of taking the table out of the definition.

**Price.** With 1.0 a broken source that delivers nothing empties the mirror (the change log keeps the rows).

**Rejected.**
- *A setting of its own for empty loads* (see 42).

## 49. A numeric keeps its precision and scale, and the target's type counts

> **Changed by decision 54.** The program alters a mirror and its change log when a value needs a wider type, for every family and not for `numeric` alone: a value that does not fit no longer fails the run. The rule that the target's type counts while every value fits stays.
>
> **Changed by decision 55.** An unconstrained `numeric` far beyond 38 digits before the point fails the run as one just beyond does; it had arrived as another value.

**Decision.** The staging table gives an Arrow `decimal128(p,s)` with a scale from 0 to its precision the type `numeric(p,s)`, from every connector; the driver would create `numeric`. A staged column whose type differs from the mirror's or the change log's only in precision or scale (`numeric` and `numeric(10,2)`) counts as the mirror's type, when every value passes into it unchanged; a value that does not fails the run and names the column, the type, the table and the value. The program never alters a mirror or a change log. The `postgres` connector delivers `numeric(p,s)` up to 38 digits as `decimal128(p,s)`, and an unconstrained `numeric` and one beyond 38 digits as `decimal256`, which arrives as `numeric`.

**Why.** The shakedown: a source value `137.00` in `numeric(12,2)` stood in the mirror as `137` (P3), and four of eight existing target tables with `numeric(10,2)` failed their first run with a change of type nobody made, whose way out, an `ALTER TABLE`, a view on the table blocked (P16). With the staged columns counted in the target's type the comparison happens in the target type (decision 2), so a second unchanged run finds nothing, and Postgres's own cast decides whether a value fits: no type table of our own. One idea carries it: a new mirror gets the source's type, an existing one keeps its own.

**Price.** A new mirror of a `numeric(p,s)` beyond 38 digits gets `numeric`, as before. A change of precision or scale in the source is not carried: the mirror keeps its type and loads while the values fit, and the first value that does not fails the run; widening is a few statements by hand, and a consumer's view on the mirror has to be dropped and created again by its owner. A mirror made by 0.1.0 keeps `numeric`, and workers of 0.1.0 fail on a mirror with `numeric(p,s)`, so every worker is updated before new tables are applied. The staging table is created empty, as `CREATE TABLE AS` with the casts from the driver's empty table, before it is filled: one round trip more per run. Checking that values fit a target's precision and scale is one scan of the staging table; a target `numeric` without them needs none, and the staging table is never altered. A negative scale or one above the precision (Postgres 15) arrives as `numeric`, since an older target cannot hold the type. `varchar(n)` still arrives as `text`: to Postgres they are two types, not one type with a length, so an existing `varchar(n)` column stays a change of type. The driver writes a decimal without its trailing zeros, so an unconstrained `numeric` `1.10` arrives as `1.1`, an equal value.

**Rejected.**
- *The program altering the mirror to the source's type.* It fails behind a view (P16), and it changes a type that consumers build on without anyone asking.
- *A schema check that ignores precision and scale.* The insert would round `1.005` into `numeric(10,2)` without a word.
- *Creating the staging table from a type table of our own.* What decision 28 rejected in pgpq.
- *Naming an unconstrained `numeric` in the field's metadata.* A second agreement between connector and core, for what `decimal256` already says.
- *Altering the staging table after filling it.* A rewrite: 0.6 to 1.0 s per 10⁶ rows measured, against 0.03 s for altering it empty.
- *Altering it at all.* Even empty, `ALTER TABLE` of 300 columns took 3.5 s, against 5 ms for `CREATE TABLE AS` with casts (ticket 15); a 0.1.0 mirror of 300 `numeric(12,2)` columns took 32 s per unchanged run with an ALTER and a scan per column, 5 s without.

**Evidence.** `tests/test_numeric.py`; the measurement in ticket 14.

## 50. `list` reads the source from the target where there is no definition

**Decision.** `rowvioli list <source>` reads the source from the definition when `--definition <dir>` is given or `sources/` is in the current directory, and otherwise from the target: the type, the sealed connection and the key id in `_rowvioli.sources`, decrypted with the private key (`ROWVIOLI_KEY_FILE`, else `worker.key`), as a run does. Nothing else changes: the connector's `tables` is called as before, the output is the same, the connection's values are scrubbed from a driver error. A new source is applied with an empty `tables` block, listed on a worker's machine, pasted, applied again. From the target `list` stops at the start, like `run` and `work` (decision 44), when the key file cannot be opened. A source removed from the definition keeps its row (`enabled = false`) and `list` still answers for it.

**Why.** The definition lives in its own repository whose pipeline runs `apply`, and that machine has no driver and no route to the source. The workers have both but, by decision 22, no checkout. `list` could run nowhere. The target holds the one thing that joins the two, and the worker holds the key.

**Price.** The source must be applied before it can be listed, which is why the empty `tables` block is allowed. The machine that lists needs the private key, so it is a worker's machine in all but name.

**Rejected.**
- *Shipping the definition to the workers.* The checkout of decision 14, which decision 22 removed.
- *Putting the drivers where the definition is.* The machine that applies would need every vendor driver and a route to every source.
- *An explicit `--from-target` flag.* A second way to say what the directory already says: a definition here wins, and where there is none the target is the only place left.

## 51. NUL bytes in text are removed while staging

**Decision.** `stage()` removes every NUL byte (0x00) from the top-level text columns (`string`, `large_string`) of each batch before it is ingested, for every connector. Text nested in a list or a struct is not cleaned, and neither is a `\u0000` escape inside a JSON value.

**Why.** Postgres `text` cannot hold 0x00, so the load failed with `invalid byte sequence for encoding "UTF8": 0x00` and the table could never be loaded. The first report came from an Informix source read through `odbc`.

**Price.** Two source values that differ only by NUL bytes become equal; in a key column that fails the run with the existing duplicate-key reason. A NUL inside a nested text still fails the run, and so does `\u0000` in a JSON value, at the change to `jsonb`. A value of NUL bytes only becomes the empty text, not null.

**Rejected.**
- *Failing with a clearer reason.* The table would still never load.
- *An option per table.* A rule to carry for one byte.

## Ninth round: the lines

On 2026-11-23 the owner asked for the output to be coloured by default and visibly better in a container too.

## 52. The same line everywhere, coloured

**Decision.** An event line has one form wherever stderr goes, a terminal, a pipe, a file, a container log or the journal: local date and time to the second, a mark (`▶` started, `✔` ok, `✘` failed, `⚠` the target is unreachable, a space otherwise), then the text. A run's line has columns: the target table padded to 28 characters, `started`, `ok` or `failed`, the seconds since its claim, and the counts as `+inserted ~updated -deleted` or the reason. The lines are coloured by default, in a pipe and a file too: the time dim, a `✔` line green, a `✘` line red, a `⚠` line yellow. No colour when `NO_COLOR` is set and not empty, when `TERM` is `dumb`, or when stderr is the systemd journal, which `JOURNAL_STREAM` says by naming the device and inode of stderr itself. Control characters in a table name or a reason are written as `?`. Output never ends a worker: without a stderr, with a closed one, or with one that cannot encode the marks, it loads on. A line that cannot be written is lost and the next is tried again: the worker writes past Python's buffer, so a failed line is not kept to fail again when the process ends, which would make the exit code 120.

**Why.** Two forms of each line, a marked one for a terminal and a plain one for a log, were two texts to keep in step, and the container, where workers run, got the plainer one. A mark and columns read at a glance in `docker logs` as at a terminal; the words `started`, `ok` and `failed` stay in the line for whoever greps or alerts on them. `docker logs`, `kubectl logs` and a terminal show the colour, and `NO_COLOR` is the convention for turning it off. The journal is the exception because escape codes are stored there: `journalctl` strips them in its usual view, but `journalctl -o json` gives such a message as an array of bytes, and `-o verbose` as `[blob data]`, so a log shipper reading the journal gets numbers. `JOURNAL_STREAM` alone is inherited by every child, whatever its stderr is, so only the comparison with stderr's own device and inode tells the journal (systemd.exec(5)).

**Price.** The line format changed: whoever reads the lines by machine (`ok after 0.4s: 0 inserted, 3 updated, 10 deleted`) has to adapt. Escape codes reach files and log collectors that do not render them, unless `NO_COLOR=1`. The legacy Windows console prints the escape codes as text; `NO_COLOR=1` is the way out. A stderr that cannot encode the marks shows them as `\u2714`. A line that fails is lost, not kept for later: a full disk loses the lines until it has room, a stderr set non-blocking that is full loses the line or the rest of it, and a pipe with no reader loses every line while the worker loads on.

**Rejected.**
- *Two forms, marked and coloured at a terminal, plain in a log* (the first build of this round). Two texts per line, and the container kept the plain one.
- *Colour only with `FORCE_COLOR`.* An opt-in that nearly nobody sets; the default is what people see, and `NO_COLOR` is there for those who need none.
- *A dashboard with a library (`rich`, `curses`).* A dependency and a second interface for what one line says; `rowvioli status` is the full view.
- *A status line that moves under the lines at a terminal* (built in this round and removed before the release). It shows only at a terminal in the foreground, where few workers run. It needed the terminal's width, a foreground check, a wipe on every way out and a writer thread so that a terminal that stops reading does not freeze the worker. `rowvioli status` shows what runs.

## Tenth round: after the shakedown of 0.4.0

## 53. A run publishes only under the target name its table has now

**Decision.** The publishing transaction ends by setting `loaded_at` only where the table is still enabled and still has the run's target schema and table. If it is not, the run fails and nothing is published, with the reason `the target name changed to raw_erp.clients while this run loaded raw_erp.customers; nothing was published, the next run loads raw_erp.clients`, or `the table left the definition while this run loaded raw_erp.customers; nothing was published`. A renamed table is new (decision 46), so its next run starts at once and loads the new name. The check is the last statement before COMMIT, and its row lock makes an `apply` that comes in between wait until the COMMIT; an `apply` that came first is seen.

**Why.** The table lock guards a table, and a run read its target name once, at its claim. An `apply` that gave the name to another table, by swapping two names or by replacing a table with another of the same name, made the other table new and due while the first was still loading, under a lock of its own: two runs on one target table, and the first published its rows into the other's mirror with status `ok`. Only the definition owns names (decision 39), so a run may publish only into a name its table still owns. A rename with no new owner fails the same way: publishing into a name nobody owns any more updates tables `apply` has just said are left behind, and the rule stays one sentence. Last in the transaction, so the run holds the row lock only for its last statements: `apply` never waits for a long publish.

**Price.** A run that loses its name meanwhile reads its source for nothing, and its first run under the new name reads it again. The check comes after the mirror is written, so a run whose writes fail first on the other table's mirror (a mirror created meanwhile, a key that now collides) fails with that error instead of the reason above, and a run that lost its name may fail a check before publishing on the other table's mirror. Nothing is published in either case. A first run that loses its name may leave its schema created and empty. The rule holds once every worker runs the version that has it: a worker of 0.4.0 still publishes under a name it lost.

**Rejected.**
- *Checking at the start of the publishing transaction with the row locked.* It would give the reason above in every case, but `apply` writes every table's row, so it would wait for every publish in progress.
- *Letting a renamed table finish into the old mirror when nobody else took the name* (decision 46 before). A second rule, for a write nobody asked for.
- *A table lock by name.* It would hold off the new owner's run, but not stop the old run from publishing afterwards.

## Eleventh round: schema changes

## 54. The mirror follows the source wherever a change log keeps what was

**Decision.** A run changes a mirror by itself wherever its change log keeps what was, and stops only where a person must decide or somebody built on what would change.

- **A column goes.** A column the source no longer has leaves the mirror and stays in the change log. The change log gets a `U` for every row that had a value in it, so replaying it still gives the mirror, and the history ends the version that had the value at the moment the column went. Rows that differ only in that column are not rewritten in the mirror. A column that comes back in the family of its old type continues its log column, with a gap in `columns__history`; one that comes back in another family begins a new column, and the old values stay under `<name>__<run>` (a retired column).
- **Families.** The exact numbers (`smallint`, `integer`, `bigint`, `numeric`), the floats (`real`, `double precision`), `date` with `timestamp`; every other type is a family of its own. A column of the family of the mirror's keeps the mirror's type while every staged value passes into it unchanged (cast to the type and back gives the same value), whatever wider type the source declares. When one does not, mirror and change log are altered to the type that holds both. A narrowed source changes nothing. A column of another family goes and comes back in one run.
- **A key.** Compared with the mirror's primary key as a set, after renames. A first key or another key replaces the mirror as a whole under the new primary key; the change log gets a `D` for every old row and an `I` for every new one at the moment of the run. The keys of a change log are its comment on the column `_op`, and the history view has one branch per key, each over its own stretch of the log, cut by `_loaded_at` and `_op`. A primary key that a person changed by hand is put back.
- **A rename.** One column gone and one come in the same run, of one family, is a rename in mirror and change log with no row written, when the data prove it (equal values in at least 20 rows, at least 5 of them different, one candidate each way) or the table says `renamed = { new = "old" }`. A consumer's view on the column keeps working under its own column name.
- **Where it stops.** A table without a change log gets only additions, widening, a changed key and a stated rename; a column that is gone or of another family stops as before, and the reason says to drop it. A column of the mirror that the change log does not have is not known to be from the source and is never dropped or written. A key column of another family, a key taken away while a change log exists, a key that no longer identifies a row, a name that the change log keeps for a retired column, and a stated rename across two families stop with a reason that says the way out. What Postgres refuses because an object of a consumer depends on it (a view, a foreign key) stops the run and names the object; nothing is published. A delivered column name longer than 63 bytes, which Postgres would cut, stops before anything is written and is named.
- **The flow.** The check makes a plan of all of this before anything is written, and every stop that follows from a rule happens there. Publishing is one transaction: it locks mirror, change log and history view in one statement with `NOWAIT`, tried again for up to ten seconds, drops the history view, carries out the plan, applies the diff, creates the view, writes the columns table, notifies on `rowvioli_schema` and checks the target name last (decision 53). A run that is ended after `max_seconds` while it widened a column says so and names the column.
- **The record.** `_rowvioli.columns` holds one row per column of a mirror and of its change log; `columns__log` and `columns__history` are its change log and history, written only by the publishing transaction, with the `_loaded_at` of the rows published in it. `by` says what caused a change: `source`, `definition`, `reader` (the version of the program or of the driver differs from that of the table's last successful run), `hand` (found by the run in the mirror or the change log) or `found` (the first fill, for what the run found and did not change; what the first run after the upgrade changes has its cause). A mirror renamed by hand appears under its new name, the old one closed. Version 4 of `_rowvioli` adds these objects and the version of the program and of the driver to `runs`; `rowvioli init` brings a version 3 target to 4 and prints the grants a worker's role needs on them, and a worker of 0.4.1 refuses version 4.
- **What the sources deliver.** A column missing from one file, one page or one run of a file or REST table is empty and never goes, when the change log says it is the source's. The driver's version is an optional entry of the connector contract, `driver_version`, and the shipped connectors report the package they read with.

**Decided by the owner during the build** (ticket 08, 2026-11-24), where it differs from the design:

1. A file or REST table without a change log stops again when a mirror column is missing from the data, with the old reason and its way out. The design emptied the column on every run, and a person's own column would have been emptied in silence.
2. `init`, bringing a target from version 3 to 4, prints the `GRANT` statements a worker's role needs on the new objects. The program grants nothing.
3. Every shipped connector says its driver's version, so that a changed driver is seen as `by = reader`.
4. Where the definition names the columns it is the catalog. A type named under `columns` that changes to another family goes and comes back like any column (a first type given to a CSV column that was loaded as `text` too), recorded `by = definition`; a column taken out of a REST table's `columns` leaves the mirror as one a database drops. The design stopped with the hint to pin it. A field named in `columns` and missing from the data is still empty and never goes. A type that a file brings itself (Parquet) in another family still stops with the hint to pin it under `columns`. Without a change log all of it stops, with the drop as the way out.
5. A type that a person changed in the mirror to another family keeps stopping, and the reason names the way out that works: drop the column from the mirror, and the next run brings it again.

**Decided after the review of ticket 08** (ticket 09, 2026-11-24):

6. A column of the mirror that the change log does not have stops the run also when the source brings its name in its family, where the design would have written the source's values over a person's. The way out the reason gives is the drop, after copying the values with the key into a table of one's own, also while the source lacks the name (ticket 10: adding the column to the change log took its values out of the mirror); a rename is none, since the renamed column stops the same. A column dropped from the change log by hand cannot be told from a person's and stops the same.
7. A pin taken out of the `columns` of a CSV, Excel or JSON table is a change of type by the definition: the column goes back to `text` or `jsonb` and comes back by the rules of item 4. A Parquet column still stops with the hint to pin it, and with the drop as the way out where a pin was taken out: the run keeps no memory of an earlier pin, and Parquet's own types can change.
8. A reason never shows a value of the source (the owner's word). A reason is read in the status view and in a worker's log by people who may not read the data. A value a type under `columns` does not take names the table, the column and the type; a `numeric` no decimal holds names its column; a value that Postgres quotes is written `"***"`. A message that a consumer's PL/pgSQL code raised, a trigger on the target or a function a source view calls, is free text and is withheld: the reason names the function, the SQLSTATE where the driver gives it, and the server log that has the message (`function guard() raised an error (SQLSTATE P0001) in the target; its message may hold a row's values, so it is left out here: the target's server log has it`, ticket 12). It is told by the SQLSTATE only `RAISE` and `ASSERT` give (`P0001`, `P0004`) and by the context the driver gives (`PL/pgSQL function guard() line 3 at RAISE`), never by the message's words. Names of tables, columns, constraints and of a consumer's object stay: the way out needs them, and Postgres's own messages of a check, unique, foreign key or not-null constraint name the constraint and show no value. The price: a person finds the row by the column, not by the reason; the message of an ODBC driver and of a connector of one's own is not covered, since a rule broad enough would hide names (`docs/open-points.md`).

Smaller departures of the build: the notification is not sent for a first fill that changed nothing; a type widened by hand in the mirror is followed in the change log by the plan, under its lock; the `file` connector marks the columns whose type a Parquet file brings itself, and only those stop at another family; a stated rename is stored with the table's options and never reaches the connector; the plan reads the key the columns table recorded for the table, so that a primary key that differs from the definition's is put back where the record has the definition's key, and, without such a record (the first run after the upgrade), as a person's where the definition is the one the table's last successful run loaded under, and otherwise by the key the change log can have been written under; where neither tells, the run stops and asks for the comment on `_op` (ticket 11 of schema changes: `runs.definition` hashes the whole definition and cannot say which table's key changed, and taking every such key for another one gave a wrong history); a retired column is recognised by its name; the text to put back a lost comment on `_op` is the latest note in the columns log that holds it.

**Why.** Before, a table whose source dropped a column failed with every run until a person ran statements by hand, which left no record and deleted the column's values from the change log. A changed key cost the whole history. Two hundred tables give such stops at night for changes that needed no decision, and nobody could say afterwards when a column went or what its type had been. One idea carries it: the change log keeps what was, so the mirror may follow the source, and every change is a change of rows and recorded like one. A run needs a person only where somebody built on what would change, and Postgres knows that: a consumer who wants to be asked builds a view on the column. A mirror keeps its type while it holds every value, so a view on it does not stop a table that loads fine. A rename is recognised only where the data prove it, because a false proof points a consumer's view at another column.

**Price.** A dropped column and a column of another family cost one change log row per row, a changed key two and a rewrite of the mirror. Widening can rewrite mirror and change log under an exclusive lock; a worker ends a run at `max_seconds`, so the first widening of a large table may need it raised once. A view on a history view stops changes to any column of it, since the history view is dropped and created again. An upgrade that delivers a type in another family writes a row per row on every affected table once. A statement prepared on a mirror fails after its columns change, until it is prepared again. A change by hand is dated when a run notices it. The numbers of the proof, 20 rows and 5 values, are strict on purpose and are constants in one place. All workers of a target must run the same drivers, or the types of a table change with the reader. The remaining limits are in `docs/open-points.md`.

**Rejected.**
- *A switch for the old behaviour, policy modes, contract files.* One flow (decision 3).
- *A stop when the reader changed, and a command that lifts it.* The change is recorded with `by = reader` and both versions, and nothing stops.
- *A rename assumed for a flag, a small table or two candidates.* A false rename is worse than a column that goes and one that comes.
- *Ending a change log by the program.* `log = false` and a key taken away still stop while a change log exists.

**Evidence.** `tests/test_columns.py`, `test_columns_go_and_come.py`, `test_types.py`, `test_keys.py`, `test_renames.py`, `test_init.py`, `test_file.py`, `test_checks.py`.

## 55. What the shakedown of schema changes found older than the branch

**Decision.** The owner had all of it fixed (ticket 12 of schema changes, 2026-11-24). Where it changes an earlier decision, that decision says so.

- **A numeric is never stored as another value** (decision 49). An unconstrained `numeric` with more digits before the point than a decimal holds fails the run and names the column, with the reason of more than 38 digits; Arrow's cast had wrapped such a value without an error, and `1.5e400` arrived as `0` with the run `ok`.
- **A table that inherits from a mirror keeps its rows** (decision 2). Every statement that reads, counts or deletes the rows of a mirror, and the first fill of a change log, names the mirror with `ONLY`, and the history view reads its change log with `ONLY`. A consumer's child table was read as part of the mirror: its rows became `D` rows, were deleted and counted towards `max_delete_share`. What alters the mirror's columns (a column that goes, a rename, a widening, a new column) still reaches the child, since Postgres keeps a child's columns those of its parent.

**Why.** Each was a fault of a promise already made: the value as the source has it.

**Evidence.** `tests/test_run_mistakes.py`, `test_checks.py`.

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
