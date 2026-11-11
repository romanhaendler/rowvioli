# Findings of the prototype

Spec: `.scratch/prototype/spec.md`. Code: `src/rowvioli/`. Tests: `tests/`. Measured on a laptop (Apple Silicon) against Postgres 16 in Docker, Python 3.13, adbc-driver-postgresql 1.13.0, pyarrow 26.0.1, PyNaCl 1.6.2.

## In short

**The model held.** One table of facts per mirror, a view that computes the rest, and the connection as the lock: that idea carried every case the spec asked for. The view is about 25 lines of SQL, and the claim is a query on it. One counting lock kept both limits under six concurrent workers. A run killed with `kill -9` at any step left the mirror unchanged, released its lock and showed `failed: worker lost`, and nothing had to clean up. A crash, a failed check and a timeout all went through the same pause formula, with no special rule. The guarantees of the README hold as written.

**It strained at the edges, not in the middle.** Almost every deviation below comes from three places:

1. **The driver.** ADBC decides the staging types. It drops `varchar(20)` to `text` and `numeric(12,2)` to `numeric`, delivers about 16 MB per batch rather than "a few thousand rows", and libpq can quote part of a password in an error.
2. **The process boundary.** The worker only knows what its run processes tell it. The run had to print its claim first so that `run` could report a killed run and the worker could enforce `max_seconds`. Stopping `work` is not designed yet.
3. **The first screen.** It shows `apply` and `work`. A newcomer also needs `init`, `key new` and two environment variables, and has to name tables by their source name.

None of this calls for a new concept. Most of it is a sentence in a document or one check in `apply`. Two points are real gaps: secret scrubbing (F1) and stopping `work` (E7).

## Test result

`uv run pytest`: **62 passed** in 108 s. No spec test is skipped or missing.

| Spec test | Covered by |
|---|---|
| 1 apply twice | `test_apply.py::test_apply_twice_gives_the_same_rows_and_keeps_what_the_workers_experienced` (compares every column except the ciphertext, which differs on every `apply` by design) |
| 2 missing variable | `test_apply.py::test_apply_with_a_missing_variable_fails_and_changes_nothing` |
| 3 two tables, one target table | `test_apply.py::test_apply_fails_when_two_tables_of_a_source_get_the_same_target_table` |
| 4 removed table | `test_apply.py::test_a_removed_table_is_disabled_and_nothing_is_deleted`, `test_run.py::test_a_disabled_table_is_not_loaded_again_and_its_mirror_stays` |
| 5 new table due at once, mirror equals source | `test_apply.py::test_apply_writes_sources_and_tables_and_new_tables_are_due_at_once`, `test_run.py::test_a_new_table_is_loaded_and_the_mirror_equals_the_source` |
| 6 counts and change log | `test_run.py::test_a_second_run_reports_the_changes_and_the_change_log_holds_exactly_them` (also `test_runs_has_one_row_per_run_...`) |
| 7 table without a key | `test_run.py::test_a_table_without_a_key_is_replaced_as_a_whole_and_has_no_change_log` |
| 8 `numeric` | `test_run.py::test_a_numeric_column_arrives_as_numeric_with_equal_values` |
| 9 reader never sees a half state | `test_crashes.py::test_a_reader_never_sees_an_empty_or_half_loaded_mirror` |
| 10 killed while filling, at the diff, while publishing | `test_crashes.py::test_a_run_killed_while_filling_...`, `test_a_run_killed_at_the_diff_or_while_publishing_...` (both modes) |
| 11 pause | `test_pause_requests.py::test_a_failed_run_pauses_one_minute_doubling_never_beyond_max_age_then_loads`, view level in `test_status.py` (pause tests) |
| 12 requests | `test_pause_requests.py`: before a run, several, during a run, followed by a failure |
| 13 order with one slot | `test_work.py::test_one_slot_loads_the_tables_in_the_order_of_how_far_they_miss_their_maximum_age` |
| 14 both limits under concurrency | `test_work.py::test_several_workers_never_exceed_parallel_per_source_nor_max_running_in_total` |
| 15 checks | `test_checks.py::test_a_check_fails_the_run_and_leaves_the_mirror_unchanged` (duplicate, null, zero rows, delete share, added column, changed type), `test_a_key_that_differs_from_the_mirrors_primary_key_fails_the_run` |
| 16 unknown type | `test_checks.py::test_an_unknown_connector_type_fails_with_a_reason_naming_the_type_and_the_worker` |
| 17 wrong private key | `test_checks.py::test_a_worker_with_the_wrong_private_key_fails_the_run_with_a_reason` |
| 18 secrets | `test_apply.py::test_the_stored_connection_and_the_output_do_not_contain_the_password`, `test_checks.py`: stored connection, copied ciphertext, failing run, refused login, driver quoting the password |
| 19 `max_seconds` | `test_work.py::test_a_run_that_exceeds_max_seconds_is_ended_and_the_status_shows_why` |
| 20 shortened `max_age` | `test_apply.py::test_a_shortened_max_age_changes_due_at_without_a_run`, `test_status.py` (same name) |
| 21 exit codes, JSON, `run <source> <table>` | `test_run.py::test_run_exits_1_when_a_table_fails_and_names_every_table_it_touched`, `test_run_ends_with_0_...`, `test_run_source_table_loads_a_table_that_is_not_due` |
| 22 `new`, `loading`, `ok`, `failed` | `test_status.py` (each state by SQL, `loading` from a lock taken by SQL), and every kill test (`loading` before the kill, `failed` after) |

Caveat for test 18: the tests use passwords that the scrubbing catches. A password with an unencoded `@` leaks in part (F1). That case is not tested.

## The seven questions

### 1. Does the view stay simple enough to read, and can the claim use it directly?

**Yes to both.** The view `_rowvioli.status` (in `src/rowvioli/schema.py`) is one `SELECT` with two small `CASE` expressions: four lines for `due_at` and four for `status`, as in the README's formula. The claim picks straight from the view. So does the worker's question "is something due". `now()` is the only clock.

Measured on the view with 10 table locks held:

| Tables | `select * from status` | the claim's pick |
|---|---|---|
| 2 | 0.3 ms | 0.4 ms |
| 200 | 1.1 ms | 1.3 ms |
| 1000 | 3.7 ms | 4.2 ms |

Claims queue behind the counting lock, so 4 ms per claim allows about 250 claims a second. That is far more than needed.

Where it strained:
- The view reads `pg_locks` once per table to decide `loading`. That is fine at 1000 tables. It is the one part whose cost grows with tables times locks.
- "Most overdue" cannot be written as the spec's `(now() - due_at) / max_age`, because Postgres cannot divide one interval by another. The claim uses `extract(epoch ...)` on both.
- The claim's pick is longer than the view: it counts the held table locks once per source and once in total. Most of its length is the `pg_locks` filter, which appears twice.
- One effect of the formula went unnoticed: a request made *during* a run that then fails makes the table due at once. `requested_at` is later than `attempted_at`, so the pause is skipped once. That is arguably right, because the request was not served. The README does not say so (A2).

### 2. Does one counting lock for the whole target hold both limits under concurrency?

**Yes.** Spec test 14 runs 6 workers with 4 slots each against two sources: erp with `parallel = 2`, crm with `parallel = 3`, 10 slow tables each, `max_running = 4`. It probes `pg_locks` every 20 ms. With the counting lock, the probe never saw more than 2 erp locks, 3 crm locks or 4 in total, and both erp's 2 and the total of 4 were reached. This held in the full suite and in ticket 06's repetitions.

To check that the lock is what holds the limit, I replaced `pg_advisory_xact_lock(0, 0)` with `SELECT 1` and re-ran the test. It failed 1 of 4 times, with 5 table locks held against a limit of 4. Ticket 06 saw 2 failures in 3 runs. Without load the race is rare: claims have to overlap within a few milliseconds, and starting a Python process spreads them out. Ticket 06's smaller first version (3 workers, 2 × 5 tables) never broke the limit even without the lock. A probe at low load proves nothing.

Decision 29 says "Evidence: none". There is evidence now.

### 3. What does a fresh process per run cost for a small table?

Measured with 10 repetitions each, a 100-row table with a key, nothing changed:

| What | Median |
|---|---|
| Bare `python -c pass` | 0.013 s |
| Python plus importing the run's modules (pyarrow, ADBC, PyNaCl) | 0.105 s |
| A run process that claims nothing (start, import, connect to the target, claim query) | 0.183 s |
| The run itself inside the target, claim to publish (`runs.finished_at - started_at`) | 0.068 s |
| `rowvioli run erp public.customers`, wall time | 0.453 s |

**About 0.18 s per run is overhead, more than twice the work for a small table.** That is irrelevant for tables loaded every few minutes. It matters only for hundreds of tiny tables per minute on one machine. Decision 25 states "about half a second" as the price, so reality is cheaper than the document.

One cost the documents do not mention: when the limits are full, every worker still starts up to `--slots` processes every 2 s, and each costs about 0.18 s. The worker's question "is something due" does not know the limits, so these processes find nothing to claim (E6).

### 4. How does the ADBC driver behave in the cases experiment 8 did not cover?

- **Refused login.** The error is `IO: [libpq] Failed to connect: ... FATAL: password authentication failed for user "..."`, with neither the URL nor the password in it (test 18, refused login). The run fails like any other, and the table goes into its pause with this reason.
- **A URL libpq cannot parse.** libpq quotes the part it choked on. With `Prozent%zz-4711` that part is the password alone, which the scrubbing removes (tested). With `p@ss%word` I observed the reason `invalid percent-encoded token: "ss%word@127.0.0.1"`. **That is part of the password, unscrubbed, in the status, in `runs` and on stdout.** See F1.
- **A killed server process.** `pg_terminate_backend` on the run's target backend: the driver raises `OperationalError: ... no connection to the server` for the running statement and again for the `ROLLBACK`. The run now answers `connection to the target lost`. The status shows `worker lost`, the lock is gone and the mirror is unchanged (`test_a_run_whose_server_process_is_killed_fails_and_run_says_so`).
- **Row counts.** `cursor.rowcount` is right for `INSERT`, `UPDATE`, `DELETE` and `CREATE TABLE AS`, and -1 otherwise. `adbc_ingest` returns the rows written. A table with a key counts from `SELECT _op, count(*) FROM _diff`. A table without a key takes its counts from `rowcount`. Tests 6 and 7 assert the counts.
- **`numeric`.** The driver reads `numeric` as an opaque string type with the typmod in the field metadata. Ingesting the strings creates a `text` column, and appending them to a `numeric` column fails. What works: the `postgres` connector casts to `decimal128(p, s)` from the typmod (`decimal256` beyond 38 digits). The staging column is then `numeric` and the values are equal, including 30 integer digits and 30 decimal places (test 8). **But precision and scale are lost.** In my run, the source's `numeric(12,2)` became plain `numeric` in the mirror. An unconstrained `numeric` with more than 38 digits on either side of the point fails the run.
- **Other types lost the same way.** `varchar(20)` arrives as `text`. The column check therefore cannot see a change from `text` to `varchar(20)` (D3).
- **Batch size.** The driver hands over a batch at about 16 MB or at the end of the stream. A small table therefore arrives as one batch. To hold a run *inside* the COPY into `_stage`, the test view has to deliver about 25 MB before the slow rows (`test_a_run_killed_while_filling_...`).
- **One statement per `execute`**, and `SHOW` is impossible, both as decision 28 says. `numeric` from the control connection comes back as a string, so it is read with `::float8`.

### 5. Can the mirror be created inside the first publishing transaction with the staging table's types?

**Yes for the mirror.** `CREATE TABLE mirror (LIKE _stage, PRIMARY KEY (...))` and `CREATE TABLE mirror__log (_run bigint, _op text, LIKE mirror)` run inside the publishing transaction. A reader never sees the mirror before COMMIT (tests 5 and 9). It inherits the driver's types, with the losses described under 4.

**Not for the schema.** Two first runs of one source both ran `CREATE SCHEMA IF NOT EXISTS`, and one failed with a unique violation (ticket 03). The schema is now created in its own statement under an advisory lock, before the publishing transaction, so an empty schema can exist without a mirror. Ticket 03 also reports that an advisory lock taken *inside* the transaction did not help. I could not re-run that experiment: the Docker host ran out of disk during this ticket. It stands as reported.

### 6. Can a run be held at each step from the SQL side, or is a hook needed?

**No hook is needed.** All three holds work and are used by the kill tests:

- **Filling.** A source view that sleeps per row. The sleep has to be per row: a volatile SQL function called with a column. `CROSS JOIN LATERAL (SELECT pg_sleep(...))` sleeps only once. With a small table this holds the run while it *reads*, before `_stage` exists, because of the 16 MB batches. To hold it inside the COPY, about 25 MB must come first.
- **Diff.** `LOCK TABLE mirror IN ACCESS EXCLUSIVE MODE` holds the run at `CREATE TEMP TABLE _diff`. This works only from the second run on, because the first run does not read the mirror.
- **Publishing.** `LOCK TABLE mirror IN EXCLUSIVE MODE` lets the diff read and holds the run at `DELETE FROM mirror`, after the change log rows have been inserted inside the transaction. After `kill -9`, neither the mirror nor the change log had changed.

The lock is released about 10 ms after `kill -9` while the backend waits for the client, and about 2 s while it waits for a lock: `client_connection_check_interval = 2s` also works during lock waits. The README's "Failures" table says under 0.3 s and under 4 s. Both hold.

### 7. Does anything in the usage need more explanation than the first screen of the README gives?

I followed the first screen with a fresh target and a source whose password has special characters. What I needed and the first screen does not say:

- **`rowvioli init` and `rowvioli key new` come first.** `apply` against a target without `init` fails with a raw SQL error (`... SQLSTATE: 42P01`). `apply` looks for `worker.pub` in the current directory, or takes `--key <file>`.
- **Two environment variables.** Without `ROWVIOLI_TARGET_URL` every command ends in a Python traceback (`KeyError: 'ROWVIOLI_TARGET_URL'`). Without `ROWVIOLI_KEY_FILE` every table failed with the reason `the connection of source erp cannot be decrypted on worker Mac:2401: 'ROWVIOLI_KEY_FILE'`. The reason is correct but cryptic.
- **A table has two names.** `run erp public.customers` takes the source table's name. `run erp customers`, the target table's name, does nothing: it prints `"tables": {}` and exits 0. So does a typo. The answer of `run` is keyed by the target table (`raw_erp.customers`).
- **Passwords inside a URL must be percent-encoded.** With `p@ss%word` the run failed and leaked part of the password (F1). With `p%40ss%25word` it worked. Nothing tells the author this.
- **The status view does not look like the first screen.** The example has one column `status` with `loading (worker etl-02)` and `failed: 62 % ...`, and a column `table`. The view has `status` and `reason` as separate columns, `source_table` and `target_table`, and no worker (A3).
- **After fixing a cause, the table waits out its pause.** Once I had set `ROWVIOLI_KEY_FILE`, both tables stayed `failed` until their pause ended or I set `requested_at`. The README covers this under "Loading now" ("after the cause of a failure has been fixed"), so it holds, but a newcomer meets it in the first five minutes.

The model itself needed no explanation: "it is due when it is older than `max_age`" was enough to predict every row of the status view.

## Deviations from the documents

Each point names what the prototype did, whether the documents hold, and what has to change. "Holds" means the documents can stay as they are, apart from an optional sentence.

### A. When a table is loaded, the status view, the claim

| # | What the prototype did | Documents hold? | What has to change |
|---|---|---|---|
| A1 | `due_at`, the pause and the four statuses are implemented as the README states. The exponent of the pause is capped at 30 doublings so that the interval cannot overflow. | Yes | Nothing. |
| A2 | A request during a run that then fails makes the table due at once, skipping the pause once. | Not covered. README "Loading now" has three rows and no row for this case. | Add the row "while loading, and the run fails: one more run at once, then the pause". |
| A3 | The view has separate `status` and `reason` columns, plus `id`, `source_id`, `source`, `source_table`, `target_table` (with schema), `max_age`, `loaded_at`, `attempted_at`, `requested_at`, `attempts`. It does not show the worker of a loading table. | No. The first screen shows `loading (worker etl-02)`, `failed: <reason>` and a column `table`. | Either change the example to the real columns, or add the worker (from the `running` row in `runs`) and a combined text. The first is less code. |
| A4 | Progress (`485,000 of about 1,000,000 rows`) is not built (out of scope). | Untested | Stays an open point. |
| A5 | The view shows a dead run as a `failed` table with reason `worker lost`. The run's row in `runs` stays `running` with no `finished_at`. Nothing ever writes `dead`. | Mostly. README: "a run as dead when it is recorded as running while nobody holds its table lock". GLOSSARY lists `dead` as a run status, as if stored. | GLOSSARY "Run status": `dead` is computed (a `running` row without its lock), never stored. If people should see it, a second small view over `runs` is needed. |
| A6 | Ordering uses `extract(epoch from now() - due_at) / extract(epoch from max_age)`. | Yes in meaning | Nothing. Only SQL examples would need it. |
| A7 | The claim takes the table lock with `pg_advisory_lock` (blocking). README shows `pg_try_advisory_lock`. Under the counting lock, the picked table is never locked, so either works. Counting is folded into the pick query. | Yes | Nothing, or align the README's SQL sketch. |
| A8 | One counting lock holds both limits (question 2). | Yes | Decision 29: replace "Evidence: none" with spec test 14 and the check without the lock. |

### B. Bookkeeping in the target

| # | What the prototype did | Documents hold? | What has to change |
|---|---|---|---|
| B1 | `sources` has the columns `target_schema`, `max_delete_share`, `max_seconds`. | No. README "Target schema" lists only `options` for them, but `options` goes to the connector unchanged. | Add the three columns to the README's list. |
| B2 | `tables.source` holds the source's name, not its id, so the README's `UPDATE ... WHERE source = 'erp'` works. The lock uses `sources.id`. | Yes | Nothing, or say so in "Target schema". |
| B3 | `meta` is one row with `schema_version` and `max_running`. | Yes | Nothing. |
| B4 | `runs.definition` (hash of the definition) is never filled. `key_id` is filled by `apply` but read by nobody. | Untested | Stays a promise of 0.1. Nothing has shown that it is needed. |
| B5 | `init` recreates the view each time and creates tables only if missing. Nothing migrates. | Yes (README says nothing) | 0.1 needs a word on schema versions. Out of scope here. |

### C. The definition and `apply`

| # | What the prototype did | Documents hold? | What has to change |
|---|---|---|---|
| C1 | Public key option: `apply <dir> --key <file>`, default `worker.pub` in the current directory. | Not covered | Name the option in "Commands". |
| C2 | `key new` writes `worker.key` (mode 600) and `worker.pub` into the current directory, both base64, and refuses to overwrite either. | Not covered (the private key file is unnamed) | Name both files and the refusal in "Commands". |
| C3 | One file may hold several sources. The file name is not compared with the source name. | Partly. "One file per source" is stated as a rule. | Say it is a convention, or let `apply` enforce it. |
| C4 | Two sources with the same `target_schema` are not detected, so their mirrors could collide. | No. README: "A schema belongs to exactly one source", but nothing checks it. | `apply` should fail on a shared `target_schema`, as it does for duplicate target tables. One check. |
| C5 | Placeholders are filled in only in string values of the `connection` block. `$` followed by anything other than an upper-case name or `$` stays as it is. | Yes | Nothing, or one sentence. |
| C6 | Ignored without an error (out of scope): `log`, table-level `max_delete_share` and `max_seconds`, and connector options. | Untested | Belongs to 0.1 and `apply --check`. |
| C7 | A removed source disables its tables too. A table or source that comes back is enabled again with its old id and history. | Yes, and nicer than stated | Optional sentence: "applying the right directory again restores everything, history included". |
| C8 | `apply` against a target without `init` ends with a raw SQL error. | Not covered | `apply` should say "run `rowvioli init` first", or `apply` could run `init` itself. That would remove one command from the first screen. |

### D. A run

| # | What the prototype did | Documents hold? | What has to change |
|---|---|---|---|
| D1 | Order of checks: zero rows, columns, key against the mirror's primary key, null key, duplicate key, then the diff, then `max_delete_share`. The share needs the deletions from the diff, so it is computed after step 5, still before publishing. | Partly. README lists the share under step 4. | Move "more than `max_delete_share` would disappear" to after the diff in "A run", or say "before publishing". |
| D2 | Without the duplicate-key check, a duplicate key did not fail: the diff turned the second row into an update, and a row went missing silently. | Yes, the check is there | Optional: say in "Checks" that this check is what prevents silent loss, not only a better reason. |
| D3 | The column check compares name and type as the staging table shows them. The driver hides `varchar(n)` and the precision of `numeric`, so a change between such types passes unseen. Columns are compared regardless of order. | No. README: "a column ... has changed its type" aborts. That holds only for types the driver tells apart. | README "Checks" and "Types": say that the types are those of the driver, and name the known losses (`varchar(n)` to `text`, `numeric(p,s)` to `numeric`). |
| D4 | `numeric` works by casting to `decimal128` in the `postgres` connector. The mirror gets `numeric` without precision and scale. Unconstrained `numeric` beyond 38 digits fails the run. | Mostly. README "Types" says the connector has to convert to `decimal128`, which is right. | Add the loss of precision and scale and the 38-digit limit. |
| D5 | The mirror is created inside the publishing transaction. The schema is created before it, in its own statement, so an empty schema may exist. | Yes for the mirror | Nothing. Optional sentence that only the schema can exist empty. |
| D6 | A table without a key reports `inserted` = rows written, `deleted` = rows that were in the mirror, `updated` = 0. Its `max_delete_share` counts shrinkage: (rows before − rows read) / rows before. Counted as deletions, every run would delete 100 %. | Not covered | One sentence each in "Comparing in the target" and in the settings table. |
| D7 | A key added to or removed from a table later fails with "the key [...] differs from the mirror's primary key []". | Yes ("a changed key is never converted") | Nothing. |
| D8 | Batches from the driver are about 16 MB. Memory per run is bounded, but by the driver's batch size. | No. Guarantee "Bounded memory: a few chunks of a few thousand rows" and GLOSSARY "Chunk: a few thousand rows". | Say "a few chunks of the size the connector delivers (about 16 MB with ADBC)". |

### E. `run` and `work`

| # | What the prototype did | Documents hold? | What has to change |
|---|---|---|---|
| E1 | The answer of `run` has `status` and `reason` for a failed table, no `step`. | No (README shows `"step": "check"`) | Drop `step` from the example. The reason already says what failed, and a step would need tracking for no decision anyone takes on it. |
| E2 | `run` has `--slots` (default 4) and loads several due tables in parallel. | Not covered | Mention `--slots` for `run` too. |
| E3 | `run` waits for tables in its scope that another worker is loading. A request during one of its own runs makes it load that table once more before it ends. | Yes ("ends when nothing is due any more") | Nothing. |
| E4 | `run <source> <table>` takes the source table's name. A name that does not exist or is disabled prints `"tables": {}` and exits 0. | Not covered | Either fail with "no such table", or document the silence. Failing is kinder (question 7). |
| E5 | A run process prints a first JSON line with its claim. This is how the worker learns which table a process holds, can report a process killed by `kill -9` as `worker lost` (exit 1), and knows when `max_seconds` starts. `max_seconds` counts from the moment the worker reads that line. | Yes in effect | Nothing outward. It is an inside detail the README's sketch of `work` omits. |
| E6 | When the limits are full, each worker still starts up to `--slots` processes every 2 s that claim nothing (about 0.18 s each), because the question "is something due" ignores the limits. | No. The README's sketch says `if something_is_due() and a_slot_is_free()`. | Make the worker's question count what is *claimable*, with the same limits as the claim (the view plus two counts), and say so in the sketch. |
| E7 | Killing `work` leaves its run processes running as orphans, and nobody ends them after `max_seconds`. There is no graceful stop. | No. "Deploying while loads are running": a new version "runs to completion ... accepts nothing new and exits". | A decision is needed. The smallest: on SIGTERM, `work` starts nothing new and waits for its runs. Then document that killing the service hard kills its runs too. |
| E8 | `max_seconds` is enforced by killing first (SIGKILL), then writing the reason through the worker's own connection, only if the run is still `running`. For a few ms the view shows `worker lost`. | Partly. README "Order when finishing: result first, then the lock" cannot hold here. Writing first would wrongly mark a run that published in between. | Add one sentence: a run ended after `max_seconds` briefly shows as `worker lost` before its reason arrives. |
| E9 | `max_seconds` exists only at source level. | Untested at table level | 0.1. |
| E10 | A run process that dies before claiming makes `run` stop starting new processes and exit 1. Before this fix it started processes forever. `work` tries again after 2 s. | Not covered | Nothing, or one line in "Failures". |
| E11 | A worker whose target goes away: the loop has no retry, so `work` would end with a traceback. With systemd `Restart=always` it would come back. Not tried. | Untested. README: "workers wait and retry". | Decide whether "retry" means the service manager restarts the worker. If so, say it. |

### F. Connections and secrets

| # | What the prototype did | Documents hold? | What has to change |
|---|---|---|---|
| F1 | Scrubbing removes every value of the connection, and for a URL its password, from every reason and output. **Observed leak:** with the password `p@ss%word` unencoded in the URL, the reason became `invalid percent-encoded token: "ss%word@127.0.0.1"`. That is part of the password, in the status, in `runs` and on stdout. | No. README: "The program removes the values of the connection from every error text". A driver quotes *parts* of values. | Two options, both small. (a) `apply` percent-encodes placeholder values that land in a URL's user info, so libpq never misparses them. (b) The sealed block also carries the raw placeholder values, and scrubbing removes those and their substrings. At least, the README must say that a password in a URL has to be percent-encoded. |
| F2 | Sealed content is `{"name": <source>, "connection": <block>}`. Opening compares the name. A copied ciphertext fails with "sealed for another source". `key_id` is the first 16 hex digits of SHA-256 of the public key. | Yes | Nothing. |
| F3 | A missing `ROWVIOLI_KEY_FILE` fails every run with the reason `... cannot be decrypted on worker ...: 'ROWVIOLI_KEY_FILE'`. A missing `ROWVIOLI_TARGET_URL` gives a traceback. | Yes in substance | `run` and `work` should check both variables at start and say which is missing. Not a document change. |
| F4 | A run process that crashes with a traceback writes it to the inherited stderr, unscrubbed. None occurred in the tests. | Untested | 0.1: scrub stderr too, or catch everything in the run process. |

### G. Numbers in the documents

| # | Document says | Observed | What has to change |
|---|---|---|---|
| G1 | Decision 25: a process per run costs "about half a second to start Python and import the libraries". | 0.105 s to import, 0.18 s for a run process up to its claim. | Replace with 0.1 to 0.2 s. |
| G2 | "Failures": lock released under 0.3 s when Postgres waits for the client, and under 4 s during a statement with a 2 s check. | About 10 ms while filling, about 2 s during a lock wait. | Holds. Optionally add that the check also works during lock waits. |

## What this means for 0.1

The carrying idea needs no change: facts in one row, everything else computed, the connection as the lock. The points that need a decision rather than a sentence are few:

1. **Secret scrubbing** (F1): encode in `apply`, or scrub raw secret values.
2. **Stopping `work`** (E7): finish the running loads, start nothing new.
3. **The worker's question** (E6): ask "is something claimable", not "is something due".
4. **One check in `apply`** (C4): a `target_schema` belongs to one source.

Everything else is wording in `README.md`, `GLOSSARY.md` and `docs/decisions.md`. The driver's type losses (D3, D4) are the price of decision 28 and should be stated, not fought.
