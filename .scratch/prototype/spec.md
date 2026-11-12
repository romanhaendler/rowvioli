# Prototype: does the model hold as a whole?

Status: resolved

## Problem Statement

rowvioli is a concept. Its parts were tried out one by one: comparing and publishing as SQL, killing a client, claiming with several workers, encrypting a value, a complete run through the ADBC driver. The model that ties them together was replaced on 2026-11-11 and exists on paper only: a maximum age per table, a definition that `apply` writes into the target, stateless workers that take whatever is most overdue, a due time that is computed and never stored, and a pause that grows after every run that did not succeed.

The owner cannot yet tell whether this model works when the parts meet, and whether using it feels as simple as the first screen of the README promises. Until that is known, a specification for version 0.1 would rest on assumptions.

## Solution

A throwaway prototype: a thin slice through the whole model with one connector. A person writes one source file, runs `rowvioli apply` and `rowvioli work`, and watches `_rowvioli.status` while tables are loaded, fail, pause and recover.

The prototype is done when the tests below pass against real Postgres databases and the questions under "Further Notes" have answers. Its code is not the start of version 0.1. What it shows goes into the documents and into the specification of 0.1.

## User Stories

1. As the owner of the concept, I want the whole model running end to end with one connector, so that I can decide whether to build version 0.1 on it.
2. As the owner, I want a list of what did not work as the documents say, so that the documents can be corrected before 0.1 is specified.
3. As a definition author, I want to describe a source in one file with its connector, connection, maximum age and tables, so that everything about a source is in one place.
4. As a definition author, I want to name every table with its key, so that nothing is loaded that I did not ask for.
5. As a definition author, I want to set a maximum age for the source and override it for a single table, so that one table can be fresher than the rest.
6. As a definition author, I want to write secrets as `$NAME` placeholders in the connection, so that no password is in the file.
7. As a definition author, I want `apply` to abort and change nothing when a variable for a placeholder is missing, so that a half-written definition never reaches the target.
8. As a definition author, I want `apply` to fail when two tables of a source would get the same target table, so that one mirror is never fed from two source tables.
9. As a pipeline, I want `apply` to be idempotent, so that I can run it on every deployment.
10. As a pipeline, I want `apply` to need only the definition, the environment, the public key and access to the target, so that I need no driver and no route to a source.
11. As an operator, I want `apply` to leave `loaded_at`, `attempted_at`, `attempts` and `requested_at` untouched, so that a deployment triggers no load and loses no request.
12. As an operator, I want a table that is removed from the definition to be disabled and its mirror to stay, so that nothing is deleted by a deployment.
13. As an operator, I want a table that is new in the definition to be loaded at once, so that I do not have to trigger the first load.
14. As an operator, I want a changed maximum age to take effect with the next query of the status view, so that I do not wait for a load to see it.
15. As an operator, I want to start a worker with nothing but the address of the target and a key file, so that a worker needs no knowledge of any source.
16. As an operator, I want to start a second worker without changing anything else, so that scaling is one more process.
17. As an operator, I want `rowvioli run` to load everything that is due once and then end, so that I can use it from cron without a service.
18. As an operator, I want `rowvioli run <source>` and `rowvioli run <source> <table>` to load now regardless of age, so that I can force a load by naming it.
19. As an operator, I want `run` to print one JSON answer and to end with exit code 1 if a table failed, so that a calling system can react.
20. As an operator, I want every table loaded in a process of its own, so that a hanging or crashing run takes only its own table with it.
21. As an operator, I want a run that exceeds `max_seconds` to be ended, so that a source that stopped answering does not occupy a slot forever.
22. As an operator, I want at most `parallel` tables of a source to load at the same time across all workers, so that a source is not overloaded.
23. As an operator, I want at most `max_running` tables to load at the same time in the target, so that workers cannot exhaust its connections.
24. As an operator, I want a worker to take the table that misses its maximum age the most, so that a five-minute table is not stuck behind hourly ones.
25. As an operator, I want a failed run to be tried again after one minute, then after 2, 4, 8 minutes, never later than one maximum age, so that a short outage is over quickly and a broken table does not hammer the source.
26. As an operator, I want a run whose worker was killed to be treated like a failed one, so that a crash needs no clean-up and no special rule.
27. As an operator, I want a run with a missing connector to fail with a reason that names the worker, so that I know which machine lacks it.
28. As an operator, I want a run whose connection cannot be decrypted to fail with a reason, so that a wrong key is visible in the status.
29. As an operator, I want the status view to show every table with its age, its due time, its status, its attempts and the reason of the last failure, so that one query tells me what the system does.
30. As an operator, I want the status view to show a table as loading only while its table lock is held, so that a dead run never looks alive.
31. As an operator, I want one row per run in a log with worker, start, end, status, counts and reason, so that I can see what happened afterwards.
32. As another system, I want to request a load by setting `requested_at` on a table, so that I can trigger a load after an event without a connector.
33. As another system, I want several requests before a run starts to cause one run, so that requesting is safe to repeat.
34. As another system, I want a request made while the table is loading to cause one more run afterwards, so that the data is never older than my request.
35. As a consumer, I want to see for every mirror the state before or after a run and nothing in between, so that I never read an empty or half-loaded table.
36. As a consumer, I want a mirror to equal its source table after a successful run, so that I can rely on it.
37. As a consumer, I want a change log next to every mirror with a key, so that I can see what was inserted, updated and deleted by which run.
38. As a consumer, I want a failed run to leave the mirror unchanged, so that a broken source never damages what I read.
39. As a consumer, I want a run to abort if the source delivers zero rows or more than `max_delete_share` of the rows would disappear, so that a broken source does not empty the mirror.
40. As a consumer, I want a run to abort if a key occurs twice or is null, so that a wrong key never produces a wrong mirror.
41. As a consumer, I want a table without a key to be replaced as a whole inside one transaction, so that it follows the same guarantee.
42. As a person responsible for security, I want the target to hold a connection as ciphertext only, so that reading the database or a backup reveals no password.
43. As a person responsible for security, I want a ciphertext copied to another source to be rejected, so that connections cannot be swapped.
44. As a person responsible for security, I want no value of a connection to appear in a reason, in the log of runs or in the output of a command, so that a failing driver does not leak a password.

## Implementation Decisions

The vocabulary follows `GLOSSARY.md`. The decisions referred to by number are in `docs/decisions.md`.

### Shape

- A Python command-line program for Python 3.11 or newer, set up as a uv project. Dependencies: `pyarrow`, `adbc-driver-postgresql`, `pynacl`. No second Postgres driver in the program (decision 28).
- Commands: `init`, `key new`, `apply`, `run`, `work`.
- Modules, each with a small interface: reading the definition and filling in placeholders; applying a definition to the target; sealing and opening connections; the control connection; one run; the worker loop; the connector registry with the `postgres` connector.
- The worker loop is one function used by `run` and `work`. `run` ends when nothing in its scope is due and nothing is loading.

### Definition

- One TOML file per source in a directory. The top-level table is the name of the source. Below it: settings, a `connection` table and a `tables` table whose entries are table names with their settings.
- Settings in the prototype: `type`, `max_age`, `parallel`, `target_schema`, `max_delete_share`, `max_seconds` at source level; `key` and `max_age` at table level. `max_age` is required at source level.
- `max_age` is a whole number with a unit: `s`, `m`, `h` or `d`.
- A placeholder is `$` followed by an upper-case name. `$$` is a literal dollar sign. A placeholder without a variable in the environment aborts `apply`.
- The target table is the last part of the source table's name in lower case, inside the target schema. `dbo.Customers` becomes `customers`. If two tables of a source resolve to the same name, `apply` fails. An override per table is left for later.

### Bookkeeping in the target

- `init` creates the schema `_rowvioli` with the tables `sources`, `tables`, `runs` and `meta` and the view `status`, as listed under "Target schema" in the README. It writes a schema version and `max_running` (default 20) into `meta`. Running `init` twice changes nothing.
- `sources.id` and `tables.id` are assigned by `apply`, starting at 1. They are the two numbers of the table lock. The pair (0, 0) is the counting lock.
- The view `status` computes per enabled table: `age`, `due_at`, `status`, and passes on `attempts` and `reason`.
  - `due_at` is: now if the table was never attempted; `requested_at` if it is later than `attempted_at`; `loaded_at` plus `max_age` if `attempts` is zero; otherwise `attempted_at` plus the pause.
  - The pause is one minute doubled for every attempt after the first, capped at `max_age`.
  - `status` is `loading` while the table lock is held, otherwise `new` if never attempted, `ok` if `attempts` is zero, `failed` in every other case. A failed table without a stored reason shows `worker lost`.
- Workers and people read the same view. Nothing derived is stored (decision 23).

### apply

- Reads the directory, fills in placeholders, encrypts each connection, and writes sources and tables by name in one transaction.
- Updates only the columns of the definition. Never writes `loaded_at`, `attempted_at`, `attempts`, `requested_at` or `reason`.
- Sources and tables that are not in the directory are disabled, never deleted.
- The public key is read from a file named by an option, by default `worker.pub` in the current directory.

### Connections

- A connection is sealed as a libsodium sealed box with the public key. The sealed content holds the name of the source and the block. Opening checks the name (decisions 15 and 26).
- `key new` writes a private key file with mode 600 and a public key file.
- A worker reads the private key from the file named by `ROWVIOLI_KEY_FILE`.
- Before a reason or an error text is stored or printed, every value of the connection is removed from it.

### Worker loop and claim

- A worker asks the target every two seconds whether something is due. For every due table, up to `--slots`, it starts a fresh process, not a fork.
- The process of a run opens the control connection and claims on it, in one transaction: take the counting lock, count the held table locks per source and in total, pick the most overdue enabled table whose source is below `parallel` while the total is below `max_running`, take its table lock, set `attempted_at`, add one to `attempts`, clear `reason`, insert a row into `runs`. If it gets nothing, it ends quietly.
- "Most overdue" is the time since `due_at` divided by `max_age`.
- A worker identifies itself by host name and process id.
- If a run's process is still alive after `max_seconds`, the worker kills it and records the reason on the table and the run through its own connection.
- The control connection sets the keepalive parameters and `client_connection_check_interval` named under "Failures" in the README. Settings are read with `current_setting`, because the driver cannot run `SHOW`.

### One run

- Steps as in "A run" in the README: claim, open the connection and call the connector, fill the TEMP staging table chunk by chunk through the driver's ingest, check, compute the diff into a TEMP table, publish, close.
- The first run of a table creates the target schema if needed and the mirror with the columns of the staging table and the key as primary key. This happens inside the publishing transaction, so a mirror never exists empty.
- Checks: key unique and not null; zero rows; `max_delete_share`; key in the definition equal to the primary key of the mirror; columns of the staging table equal to the columns of the mirror. Any difference in columns fails the run in the prototype.
- Every table with a key has a change log. A table without a key is replaced as a whole in one transaction and has none.
- Publishing sets `loaded_at` to the time of publishing and `attempts` to zero in the same transaction as the mirror.
- A run that fails writes its reason to the table and to its row in `runs`, with the status `failed`, and closes the connection. Status first, then the lock.
- Column lists in the comparison are generated by name, never with `*` (experiment 6).

### Connector

- The contract is `read(connection, table, options)` returning Arrow batches (decision 27).
- The registry is a mapping from `type` to a function. It contains `postgres` only. An unknown `type` fails the run with a reason that names the type and the worker.
- The `postgres` connector expects the field `url` and reads the whole table through ADBC as a stream of batches.
- `numeric` columns are a known trap: the driver reads them as text (see "Types" in the README). The prototype has to show a way in which a `numeric` column of the source becomes a `numeric` column of the mirror with equal values.

### Answer of run

- One JSON object on stdout with the duration and, per target table touched in this call, its status, counts or reason.
- Exit code 0 if no table failed, 1 otherwise.

## Testing Decisions

- **One seam.** Tests start the commands as real processes against two real PostgreSQL databases in Docker, a source and a target. They look only at what a user sees: the view `status`, the mirrors and change logs, the table `runs`, stdout and the exit code. No test imports a module of the program.
- **A good test** states a guarantee from the README and would still pass if the inside of the program were rewritten.
- **No simulated clock.** A test that needs time to pass moves a point in time in `_rowvioli.tables` back with SQL, for example `attempted_at` by two minutes, instead of waiting. Definitions in tests use maximum ages of seconds.
- **Crashes are real.** A test kills the process of a run with `kill -9`.
- **Stopping a run at a step needs no hook in the program.** A source view with a sleep per row holds it while it fills the staging table. A lock on the mirror that blocks reads holds it at the diff. A lock on the mirror that blocks only writes holds it at publishing.
- **Tests may use any Postgres driver** to observe and to prepare data.

What is tested:

1. `apply` twice gives the same rows, and what the workers experienced is unchanged.
2. `apply` with a missing variable exits with an error and changes nothing.
3. `apply` with two tables resolving to one target table fails.
4. A table removed from the definition is disabled, its mirror stays, and it is not loaded again.
5. A new table is due at once. After `run`, the mirror equals the source table in both directions.
6. After changes in the source, a second run reports the right counts of inserted, updated and deleted rows, the mirror equals the source again, and the change log holds exactly these rows.
7. A table without a key is replaced as a whole and has no change log.
8. A `numeric` column arrives as `numeric` with equal values.
9. A reader that queries the mirror in a loop during many runs never sees zero rows and never a row count between the old and the new state.
10. A run killed while filling, while computing the diff and while publishing leaves the mirror unchanged, releases the table lock, and shows the table as `failed` with `worker lost`.
11. After a failed or killed run the table is not due for one minute. With `attempted_at` moved back it is loaded. After three attempts the pause is four minutes. The pause never exceeds the maximum age.
12. A request before a run causes one run. Several requests cause one run. A request during a run causes one more run. A request followed by a failure leaves the table in its pause.
13. With one slot and several due tables, the tables are loaded in the order of how far they miss their maximum age.
14. With several workers and more due tables than allowed, a probe on `pg_locks` never finds more table locks of a source than `parallel`, and never more in total than `max_running`.
15. A duplicate key, a null key, zero rows, a deletion above `max_delete_share`, a key that differs from the mirror's and a changed column each fail the run, leave the mirror unchanged and show their reason in the status.
16. A source with an unknown `type` fails with a reason that names the type and the worker.
17. A worker with the wrong private key fails the run with a reason.
18. The stored connection does not contain the password. A ciphertext copied to another source is rejected. The password appears in no reason, no row of `runs` and no output, also when the source refuses the login.
19. A run that exceeds `max_seconds` is ended, and the status shows why.
20. A shortened maximum age changes `due_at` in the status view without any run.
21. `run` ends with exit code 0 when all tables succeed and 1 when one fails, and its JSON names every table it touched. `run <source> <table>` loads a table that is not due.
22. The status view shows `new`, `loading`, `ok` and `failed` in the situations above.

Prior art: the scripts in `experiments/`. Experiment 4 kills a client and checks the lock. Experiment 5 probes `pg_locks` every 20 ms to prove a limit. Experiment 8 uses a second connection as an observer and checks what is visible before and after a COMMIT.

## Out of Scope

- The connectors `odbc`, `file` and `rest`, and entry points for connector packages.
- `rowvioli list` and `apply --check`.
- Progress of a running run in the status view.
- Adding a new column of the source to the mirror. Any change of columns fails the run.
- The switch `log = false` and an override for the name of a target table.
- Options passed to connectors.
- A target address with several nodes, failover, and a connection pooler.
- Database roles and rights. The prototype uses one user.
- Rotation of the key pair.
- Machine or network failure, where no process closes the connection.
- Packaging for PyPI, the quickstart, the example Dockerfile and the benchmark.
- Performance beyond what the tests need. Measurements stay with `experiments/`.
- Updating `README.md`, `GLOSSARY.md` and `docs/`. That follows from the findings and is a step of its own.

## Further Notes

The prototype is throwaway. Clarity of what was learned matters more than the quality of its code.

It should answer these questions, each with what was observed:

1. Does the view that computes `due_at` and `status` stay simple enough to read, and can the claim use it directly?
2. Does one counting lock for the whole target hold both limits under concurrency? Experiment 5 used one per source and had no total limit.
3. What does a fresh process per run cost for a small table?
4. How does the ADBC driver behave for what experiment 8 did not cover: a refused login, a killed server process, row counts, a `numeric` column?
5. Is creating the mirror inside the first publishing transaction possible with the staging table's types as the driver creates them?
6. Can a run be held at each step from the SQL side as the tests assume, or is a hook needed?
7. Does anything in the usage need more explanation than the first screen of the README gives?

The findings are reported to the owner as a list that names, for each point, whether the documents hold, and what has to change in them.
