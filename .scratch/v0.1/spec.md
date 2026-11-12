# Version 0.1: the program

Status: ready-for-agent

## Problem Statement

rowvioli exists as a concept and as a throwaway prototype. The prototype showed that the model holds as a whole (`.scratch/prototype/findings.md`), and the documents were corrected from its findings on 2026-11-12. There is still no program anybody can install.

A team that wants to mirror tables from a Postgres database or from files into a Postgres target cannot use rowvioli yet. They would have to write their own loader, scheduler and bookkeeping, and they would get none of the guarantees: never a half-loaded table, never two runs on the same table, retries without bookkeeping, a status that one query answers.

## Solution

Version 0.1 as `docs/package.md` describes it: a command-line program, installable with `uv tool install rowvioli`, with the commands `init`, `key new`, `list`, `apply` (with `--check`), `run` and `work`, the connectors `postgres` and `file`, and connectors from other packages through an entry point. A quickstart shows the whole usage with one `docker compose up`.

The README is the behaviour reference. Whatever it says about these commands, connectors and guarantees is what 0.1 does. Where the README and this spec differ, this spec wins and the README is corrected as part of the work.

The program is written anew. The prototype's code is not its start, but the prototype's tests are: they only look at what a user sees, so they carry over as the starting suite.

## User Stories

### Defining a source

1. As a definition author, I want to describe a source in one TOML file with its connector, connection, maximum age and tables, so that everything about a source is in one place.
2. As a definition author, I want to name every table with its key, so that nothing is loaded that I did not ask for.
3. As a definition author, I want to use a composite key, so that tables identified by several columns can be mirrored.
4. As a definition author, I want to set `max_age`, `max_delete_share`, `max_seconds` and `log` for a source and override them for a single table, so that one table can behave differently from the rest.
5. As a definition author, I want `log = false` to switch off the change log of a table, so that large tables that change a lot do not grow a second table forever.
6. As a definition author, I want any other key at source or table level to reach the connector as an option, so that a connector can be told how to read without a change to the program.
7. As a definition author, I want to write secrets as `$NAME` placeholders, so that no password is in the file.
8. As a definition author, I want to write a password with `@` or `%` in it as it is, so that I never percent-encode anything by hand.
9. As a definition author, I want `rowvioli list <source>` to print the tables of a source with their keys in the definition's format, so that I do not type 200 table names.
10. As a definition author, I want `rowvioli apply --check` to check my definition without a target and without the secrets, so that a merge request pipeline can reject a broken definition before it is merged.

### Applying a definition

11. As a pipeline, I want `apply` to be idempotent, so that I can run it on every deployment.
12. As a pipeline, I want `apply` to need only the definition, the environment, the public key and the target, so that I need no driver and no route to a source.
13. As a pipeline, I want `apply` to abort and change nothing when a variable is missing, two tables of a source get the same target table, two sources share a `target_schema`, or the target has no schema `_rowvioli`, so that a half-written definition never reaches the target.
14. As a pipeline, I want `apply` against a target without `init` to tell me to run `rowvioli init` first, so that I do not have to decode an SQL error.
15. As an operator, I want `apply` to leave `loaded_at`, `attempted_at`, `attempts` and `requested_at` untouched, so that a deployment triggers no load and loses no request.
16. As an operator, I want a source or table removed from the definition to be disabled while its mirror stays, and to come back with its history when it is added again, so that a wrong deployment is undone by the right one.
17. As an operator, I want a table that is new in the definition to be loaded at once, so that I do not have to trigger the first load.
18. As an operator, I want a changed maximum age to take effect with the next query of the status view, so that I do not wait for a load to see it.
19. As an operator, I want every run to record a hash of the definition it ran with, so that I can tell which deployment a run belonged to.

### Setting up

20. As an operator, I want `rowvioli init` to create the schema `_rowvioli` and to change nothing when run again, so that I can run it safely.
21. As an operator, I want every command to refuse to work against a target whose schema version is not its own, and to name both versions, so that two program versions never write the same bookkeeping differently.
22. As an operator, I want `rowvioli key new` to write `worker.key` with mode 600 and `worker.pub`, and never to overwrite either, so that I cannot lose a key by typing the command twice.
23. As an operator, I want a worker's key file to hold more than one private key, so that I can rotate the key pair without stopping the workers.
24. As an operator, I want `run` and `work` to tell me at start which of `ROWVIOLI_TARGET_URL` and `ROWVIOLI_KEY_FILE` is missing, so that I do not read a traceback or a failed status for a missing variable.

### Loading

25. As an operator, I want to start a worker with nothing but the address of the target and a key file, so that a worker needs no knowledge of any source.
26. As an operator, I want to start a second worker without changing anything else, so that scaling is one more process.
27. As an operator, I want `rowvioli run` to load everything that is due once and then end, so that I can use it from cron without a service.
28. As an operator, I want `rowvioli run <source>` and `rowvioli run <source> <table>` to load now regardless of age, so that I can force a load by naming it.
29. As an operator, I want `run <source> <table>` with an unknown or disabled name to fail, so that a typo is not mistaken for success.
30. As an operator, I want `run` to print one JSON answer and to end with exit code 1 if a table failed, so that a calling system can react.
31. As an operator, I want every table loaded in a process of its own, so that a hanging or crashing run takes only its own table with it.
32. As an operator, I want a run that exceeds `max_seconds` to be ended and the reason shown, so that a source that stopped answering does not occupy a slot forever.
33. As an operator, I want at most `parallel` tables of a source and at most `max_running` tables in total to load at the same time across all workers, so that neither a source nor the target is overloaded.
34. As an operator, I want a worker to start a run process only when something is claimable, so that full limits do not cost a process every two seconds per slot.
35. As an operator, I want a worker to take the table that misses its maximum age the most, so that a five-minute table is not stuck behind hourly ones.
36. As an operator, I want a failed or killed run to be tried again after one minute, then after 2, 4, 8 minutes, never later than one maximum age, so that a short outage is over quickly and a broken table does not hammer the source.
37. As an operator, I want `work` on SIGTERM to start nothing new, let its runs finish and exit, so that a deployment of a new program version loses no load.
38. As an operator, I want a worker whose target is unreachable to wait and try again, so that a restart or failover of the target needs nobody to restart the workers.
39. As an operator, I want a run with a missing connector, an undecryptable connection or a ciphertext of another source to fail with a reason that names the worker, so that I know which machine to fix.

### Watching

40. As an operator, I want the status view to show every enabled table with its source table, target table, maximum age, age, due time, status, attempts and reason, so that one query tells me what the system does.
41. As an operator, I want the status view to show a table as `loading` only while its table lock is held, and a dead run as `failed` with the reason `worker lost`, so that a dead run never looks alive.
42. As an operator, I want the status view to show how many rows a loading table has written so far and how many the last run had, so that I can tell a slow load from a stuck one.
43. As an operator, I want one row per run in `_rowvioli.runs` with worker, start, end, status, counts and reason, so that I can see what happened afterwards.

### Requesting

44. As another system, I want to request a load by setting `requested_at`, so that I can trigger a load after an event without a connector.
45. As another system, I want several requests before a run to cause one run, a request during a run to cause one more run, and a request during a run that fails to cause one more run at once, so that the data is never older than my request.

### Consuming

46. As a consumer, I want to see for every mirror the state before or after a run and nothing in between, so that I never read an empty or half-loaded table.
47. As a consumer, I want a mirror to equal its source table after a successful run, so that I can rely on it.
48. As a consumer, I want a change log next to every mirror with a key, unless switched off, so that I can see what each run inserted, updated and deleted.
49. As a consumer, I want a new column of the source to appear in the mirror and its change log, so that additions need nobody.
50. As a consumer, I want a missing column, a changed type, a changed key, a duplicate or null key, zero rows, or more deletions than `max_delete_share` to fail the run and leave the mirror unchanged, so that a broken source never damages what I read.
51. As a consumer, I want a table without a key to be replaced as a whole inside one transaction, so that it follows the same guarantee.
52. As a consumer, I want a `numeric` column of a Postgres source to arrive as `numeric` with equal values, so that money is not turned into text or floats.

### Files

53. As a definition author, I want to mirror CSV, Excel and Parquet files with the `file` connector, so that spreadsheets and exports land in the target like any table.
54. As a definition author, I want CSV and Excel columns to arrive as text unless I name their types, so that a type never flips between two runs because of the rows a sniffer happened to see.
55. As a definition author, I want to pass reading options such as a separator or a sheet, so that files that are not in the default format can be read.

### Connector authors

56. As a connector author, I want to write one function `read(connection, table, options)` that yields Arrow batches and register it through the entry point group `rowvioli.connectors`, so that my package works without a change to rowvioli.
57. As a connector author, I want to offer an optional `tables(connection)` for `rowvioli list`, so that users of my connector can generate their definition too.

### Security

58. As a person responsible for security, I want the target to hold a connection as ciphertext only, so that reading the database or a backup reveals no password.
59. As a person responsible for security, I want a ciphertext copied to another source to be rejected, so that connections cannot be swapped.
60. As a person responsible for security, I want no value of a connection to appear in a reason, in `runs`, on stdout or on stderr, also when a driver or connector fails with the value in its message, so that a failing driver does not leak a password.

### Getting started and shipping

61. As a newcomer, I want a quickstart that runs with one `docker compose up` and ends with a loaded mirror and a status view to look at, so that I see the whole usage in five minutes.
62. As a team adopting rowvioli, I want a template for the repository that holds the definition, so that I start with the right layout and pipeline.
63. As an operator who runs containers, I want an example Dockerfile into which I put my own drivers, so that I can build a worker image without an official one.
64. As the owner, I want the test suite to run on Linux in CI on every push, so that the program is proven where workers will run.
65. As the owner, I want a release workflow that publishes to PyPI once the project name is registered, so that a release is one tag.
66. As the owner, I want a benchmark script that reproduces the README's measurement table, so that the numbers stay true as the code changes.

## Implementation Decisions

The vocabulary follows `GLOSSARY.md`. Decisions referred to by number are in `docs/decisions.md`; the third round (32-35) came from the prototype. The behaviour reference is `README.md`. The prototype's findings, with what was observed and measured, are in `.scratch/prototype/findings.md`; its code is on branch `prototype-impl` and may be read for how a problem was solved, not copied as a base.

### Shape

- A Python package for Python 3.11 or newer, set up as a uv project, MIT licence. Core dependencies: `pyarrow`, `adbc-driver-postgresql`, `pynacl`. The extra `file` adds `duckdb`. No second Postgres driver in the program (decision 28).
- Modules as `docs/package.md` lists them, each with a small interface: commands and the answer of `run`; reading and checking the definition and filling in placeholders; applying the definition; sealing and opening connections; the control connection; one run; the worker loop; the connector contract and registry; the `postgres` and `file` connectors; the SQL of the schema, the status view, the claim and the diff.
- The worker loop is one function used by `run` and `work`. `run` ends when nothing in its scope is due and nothing is loading.

### Bookkeeping in the target

- `init` creates the schema `_rowvioli` with `sources`, `tables`, `runs`, `meta` and the view `status`, with the columns listed under "Target schema" in the README. Running it again changes nothing.
- **Schema version 1.** `init` writes schema version 1 into `meta`. Every command that uses the target refuses to work if the version there differs from the program's, and names both. Moving a schema from one version to the next is left for the first version that needs it. (Decides open point B5.)
- `sources.id` and `tables.id` are assigned by `apply`, from 1. They are the two numbers of the table lock. (0, 0) is the counting lock.
- The view `status` computes per enabled table `age`, `due_at` and `status` as the README's formula states, and passes on `attempts` and `reason`. It shows `loading` only while the table lock is held, and `worker lost` for a failed table without a stored reason.
- **Progress.** While a table is loading, the view shows the rows written so far, from `pg_stat_progress_copy` of the lock holder's backend, and the rows read by the last successful run. It shows nothing when the progress is not visible to the reading role (decision 31). Whether another role sees it stays unverified.
- `meta` holds `schema_version`, `max_running` (default 20) and the hash of the definition last applied. A run copies that hash into its row in `runs` when it claims.
- Nothing derived is stored (decision 23).

### Definition and `apply`

- One TOML file per source by convention, several sources per file allowed. Settings as in the README's table under "Defining a source". `max_age` is required at source level, a whole number with `s`, `m`, `h` or `d`.
- A placeholder is `$` followed by an upper-case name; `$$` is a literal `$`. Placeholders are filled in only in the string values of the `connection` block.
- **Percent-encoding (decision 32).** When a placeholder lands in the user-info part of a URL value (`scheme://user:pass@host`), its value is percent-encoded before sealing.
- The target table is the last part of the source table's name in lower case, inside `target_schema` (default `raw_<source>`).
- `apply` fails, changing nothing, on: a missing variable; two tables of a source with the same target table; two sources with the same `target_schema` (decision 35); a target without `_rowvioli`, with the message to run `rowvioli init` first.
- `apply` writes sources and tables by name in one transaction, updates only the definition's columns, and disables what is missing. A source or table that comes back is enabled again with its old id.
- `apply --check` reads and checks the definition without a target and without the environment: syntax, required settings, units, keys, duplicate target tables, shared target schemas, well-formed placeholders. It never fills in a placeholder.
- The public key is read from `--key <file>`, by default `worker.pub` in the current directory. `apply` stores its `key_id` next to each ciphertext.

### Connections and keys

- Sealed box with the public key; the sealed content holds the source name and the block; opening checks the name (decisions 15, 26).
- `key new` writes `worker.key` (mode 600) and `worker.pub` into the current directory and refuses to overwrite either.
- The file named by `ROWVIOLI_KEY_FILE` holds one or more private keys, one per line. A run picks the key whose `key_id` matches the source's. This is what makes the rotation in the README work.
- Before a reason or error text is stored or printed, every value of the connection, and the password of any URL in it, is removed from it.
- **Nothing unscrubbed on stderr.** The run process catches every exception and turns it into a scrubbed reason. If it still dies, the worker reports it as `worker lost`. (Decides open point F4.)

### Worker loop and claim

- A worker asks the target every two seconds whether something is **claimable**: due and within `parallel` and `max_running`, with the same counts as the claim (decision 34). For each claimable table, up to `--slots`, it starts a fresh process.
- The run process claims on its control connection as the README's "How Postgres counts" shows, in one transaction under the counting lock. Most overdue is the time since `due_at` divided by `max_age`, both in seconds. If it gets nothing, it ends quietly.
- The run process reports its claim to the worker before it starts reading, so the worker knows which table a process holds, can report a process that died as `worker lost`, and starts the clock for `max_seconds` there.
- A worker identifies itself by host name and process id.
- `max_seconds` (source or table) is enforced by the worker: it kills the run's process and then records the reason on the table and the run through its own connection, if the run is still `running`.
- **SIGTERM (decision 33).** `work` starts nothing new, waits for its runs and exits 0. A second SIGTERM or SIGKILL is not handled specially.
- **Target unreachable.** When the worker's own connection fails, it waits two seconds and connects again, as long as it runs. Its run processes fail on their own and are retried after the pause. (Decides open point E11: the worker retries itself, the service manager is not needed for it.)
- `run` and `work` check `ROWVIOLI_TARGET_URL` and `ROWVIOLI_KEY_FILE` at start and name the missing one.
- `run <source> <table>` names the table as in the source. An unknown or disabled name fails with exit code 1 before anything is loaded. `run <source>` and `run <source> <table>` set `requested_at` and load until nothing in their scope is due.
- The control connection sets the keepalive parameters and `client_connection_check_interval` from "Failures" in the README.

### One run

- Steps as in "A run" in the README: claim, open the connection and call the connector, fill the TEMP staging table chunk by chunk through the driver's ingest, check, compute the diff into a TEMP table, check the share of deletions, publish, close.
- The first run of a table creates the target schema under an advisory lock before publishing, and the mirror and change log inside the publishing transaction, so a mirror never exists empty.
- **Schema changes (decision 17).** A new column of the source is added to the mirror and its change log inside the publishing transaction, under a `lock_timeout`. A missing column, a changed type (as the driver shows it) or a key that differs from the mirror's primary key fails the run.
- Checks: zero rows; columns; key against the mirror's primary key; key unique and not null; after the diff, `max_delete_share`. A table without a key counts its shrinkage against `max_delete_share`.
- Every column list in comparison and publishing is generated by name, never with `*` or by position.
- Publishing sets `loaded_at` and `attempts = 0` and finishes the run's row in the same transaction as the mirror. A table without a key is replaced as a whole in that transaction and has no change log.
- A run that fails writes its reason to the table and its row in `runs` with the status `failed`, then closes the connection: status first, then the lock.

### Connectors

- The contract is `read(connection, table, options)` returning an iterator of Arrow batches, optionally `tables(connection)` returning tables with their keys (decision 27).
- Connectors are found through the entry point group `rowvioli.connectors`. The shipped `postgres` and `file` register the same way. An unknown `type` fails the run with a reason that names the type and the worker.
- `postgres`: expects `url`, reads the whole table through ADBC as a stream of batches, converts `numeric` to `decimal128(p, s)` from the column's type modifier (`decimal256` beyond 38 digits). `tables` lists the tables with their primary keys.
- `file`: expects `path`, a directory. The table is a file name relative to it. Built on DuckDB, reads CSV, Excel and Parquet by extension, delivers batches. Parquet keeps its own types. CSV and Excel deliver every column as text unless the option `columns` names types. Options such as a separator or a sheet name are passed to DuckDB. `tables` lists the files in the directory, without keys.
- `list <source>` reads the definition and the environment, opens the connection, calls `tables` and prints TOML ready to paste into the source's `tables` block. A connector without `tables` fails with a clear message.

### Answer of `run`

- One JSON object on stdout with the duration and, per target table touched, `status` and the counts or the `reason`. No `step`. Exit code 0 if no table failed, 1 otherwise.

### Shipping

- `examples/quickstart`: a compose file with a source Postgres, a target Postgres and a container that runs `init`, `key new`, `apply` and `run` against one source file, so that `docker compose up` ends with a loaded mirror.
- `examples/definition`: the template for the definition repository from "Operation" in the README, with a pipeline that runs `apply --check` on merge requests and `apply` after a merge.
- `examples/Dockerfile`: the program plus a place for the operator's drivers.
- `bench/`: one script that reproduces the README's measurement table at 10⁶ rows.
- CI on GitHub Actions: the test suite on Linux on every push; a release workflow that publishes to PyPI from a tag through trusted publishing. Registering the name on PyPI is the owner's step.

## Testing Decisions

- **One seam.** Tests start the commands as real processes against two real PostgreSQL databases in Docker, a source and a target, and look only at what a user sees: the view `status`, the mirrors and change logs, the table `runs`, files on disk, stdout, stderr and the exit code. No test imports a module of the program. The owner confirmed this seam on 2026-11-12.
- **The prototype's tests are the starting suite.** They were written against this seam, so they carry over. Where 0.1 changes behaviour on purpose, the test changes with it: a new column is now added instead of failing; `run` with an unknown table now fails; the status view's columns are as in the README.
- **A good test** states a guarantee or a sentence of the README and would still pass if the inside of the program were rewritten. A test never matches the program's own SQL text or the names of its TEMP tables.
- **No simulated clock.** A test that needs time to pass moves a point in time in `_rowvioli.tables` back with SQL. Definitions in tests use maximum ages of seconds.
- **Crashes are real.** A test kills a run's process with `kill -9`, ends `work` with SIGTERM, and makes the target unreachable with `ALTER DATABASE ... ALLOW_CONNECTIONS false` plus `pg_terminate_backend` instead of stopping a container.
- **Holding a run needs no hook.** A source view with a per-row sleep holds it while filling; a lock on the mirror holds it at the diff or at publishing (`.scratch/prototype/issues/05-crashes-pause-requests.md`, comments).
- **The file connector** is tested through the same seam with files the test writes into a temporary directory.
- **A foreign connector** is a tiny package inside the test tree, installed into the test environment, registered under a test type through the entry point group. It also serves to make a connector fail with connection values in its message, for the scrubbing tests.
- **Tests may use any Postgres driver** to observe and prepare data.
- **Disk space.** The harness removes its containers together with their volumes and leaves nothing behind after a session. Several worktrees may run the suite at once, so containers use random free ports and unique names. On 2026-11-11 leaked volumes filled the owner's disk.

What is tested, in addition to the prototype's 22 tests (`.scratch/prototype/spec.md`, "Testing Decisions"), each through the seam:

1. `init` twice changes nothing; a target with another schema version is refused by every command, naming both versions.
2. `apply` against a target without `init` fails with the message to run `rowvioli init` first.
3. `apply` fails when two sources share a `target_schema`.
4. `apply --check` passes a valid definition and fails each invalid one, with no target reachable and no variable set.
5. A password with `@` and `%` written plainly loads the table; with the source refusing it, no part of it appears in any reason, row of `runs`, stdout or stderr.
6. A connector that fails with connection values in its message leaks none of them, also when it raises from deep inside.
7. `run` and `work` without `ROWVIOLI_TARGET_URL` or `ROWVIOLI_KEY_FILE` end at once naming the missing variable.
8. `run <source> <table>` with an unknown or disabled name exits 1 and loads nothing.
9. `work` on SIGTERM while a run is held lets the run publish, starts nothing new, and exits 0.
10. With the limits full, the number of the target's connections stays at the running tables plus one per worker over many polling intervals.
11. A worker survives an unreachable target and loads again once the target accepts connections.
12. A new source column appears in the mirror and the change log, with values; a dropped column and a changed type each fail the run and leave the mirror unchanged.
13. `log = false` gives no change log; table-level `max_delete_share` and `max_seconds` override the source's.
14. A composite key mirrors and logs correctly.
15. The `file` connector mirrors a CSV, an Excel and a Parquet file; CSV and Excel arrive as text unless `columns` names types; a separator option is honoured; a missing file fails with a reason.
16. A foreign connector installed through the entry point loads a table.
17. `list` for `postgres` and `file` prints TOML that, pasted into a definition, applies and loads.
18. While a run is held filling, the status view shows rows written so far greater than zero.
19. Every run carries the hash of the definition applied before it; a changed definition gives a different hash.
20. Key rotation as in the README: with old and new private key in the key file, a worker loads after `apply` with the new public key; with only the old one, the run fails with a reason.
21. The quickstart: `docker compose up` in `examples/quickstart` ends with a loaded mirror. Runs as its own CI job, not in the main suite.

Prior art: the prototype's suite on branch `prototype-impl` (`tests/`), the experiments in `experiments/`.

## Out of Scope

- The connectors `odbc` and `rest` (0.2) and JSON files in the `file` connector.
- The command `request`, reading only rows from a timestamp on, patterns for table names, workers that serve only some sources.
- Migrating the schema from one version to the next.
- A view that shows dead runs as such (open point A5).
- The web UI.
- Creating database roles. Tests use one user; whether progress is visible to another role stays unverified.
- A target address with several nodes and failover: the URL is passed to the driver unchanged, nothing is tested.
- Machine or network failure, where no process closes the connection.
- Validity periods computed from the change log.
- Registering the name on PyPI, GitHub or a domain, and the trademark search.
- Performance work beyond the benchmark script.

## Further Notes

- The README is the reference, and it describes more than 0.1 (for example `odbc` in its first example). Corrections that 0.1 forces go into the README, the glossary and `docs/` in the same change as the code.
- Open points E11, B5 and F4 are decided above; `docs/open-points.md` records that.
- The owner values one carrying idea over a pile of rules. When something in the implementation needs a new rule or a long explanation, that is a signal to stop and ask, not to add it.
- Watch the disk: check free space before starting the suite or parallel work, and stop if it runs low.
