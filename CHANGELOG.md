# Changelog

## Unreleased

Added:

- **The mirror follows the source where a change log keeps what was** (decision 54). A table with a key and a change log no longer stops at a changed shape:
  - A column the source drops leaves the mirror and stays in the change log and the history, with a `U` for every row that had a value. One that comes back in its old family continues its log column; in another family the old values stay under `<name>__<run>`, a retired column, which the change log's comment on it says (`{"retired": "<name>"}`).
  - A type of the same family is kept while every value fits and widened, in mirror and change log, when one does not. A type of another family is a column that goes and comes back. This replaces the handling of `numeric` alone: a value that does not fit a `numeric(p,s)` no longer fails the run.
  - Another key replaces the mirror as a whole and keeps the history: the change log gets a `D` per old row and an `I` per new one, and the history view has a branch per key. A first key adds the primary key and begins the change log; the same columns in another order are the same key; a primary key changed by hand is put back.
  - A column the data prove renamed, or the table says is, is renamed in mirror and change log with no row written, and a consumer's view on it keeps working.
  - A run stops where a consumer's view, foreign key or other object depends on what would change; Postgres refuses, nothing is published and the reason names the object.
- `renamed = { new = "old" }`, a setting of a table for a rename the data cannot prove (docs/definition.md).
- `_rowvioli.columns`, `columns__log` and `columns__history`: which columns and types every mirror and change log had at a moment, what caused each change (`source`, `definition`, `reader`, `hand`, `found`) and a note. `NOTIFY` on `rowvioli_schema` when a run commits a change of columns, key or name, not for a first fill that changes nothing. Queries in docs/target.md.
- Version 4 of `_rowvioli`: `rowvioli init` brings a target of version 3 to 4, changes nothing else and prints the `GRANT` statements a worker's role needs. `_rowvioli.runs` records the version of the program and of the driver. A connector may report its driver's version (`driver_version`); the shipped ones report the package they read with. A connector may say that it has no catalog (`catalog = "data"` as `file` says, `"definition"` as `rest` says) and gets their rules for a missing column (docs/connector-guide.md).
- A field named under `columns` that a file lacks is empty, in every reader and in a pattern, as in REST. Before, DuckDB's `Binder Error` failed the run.

Changed (a working set-up can notice these):

- **After `rowvioli init` brings a target to version 4, a worker's role needs `GRANT SELECT, INSERT, UPDATE, DELETE ON _rowvioli.columns` and `GRANT SELECT, INSERT ON _rowvioli.columns__log`** (`init` prints them on that upgrade). Without them every publish fails with `permission denied`. Auditors and consumers who read the columns need `SELECT` on `_rowvioli.columns__history` and nothing else. All workers of a target run the same drivers. A worker of 0.4.1 refuses version 4, and every command of this version but `init` and `status` refuses version 3: stop the old workers, run `init`, grant, start the new ones (docs/operation.md).
- A change log is complete from its last change of key: replaying it from there gives the mirror.
- A changed key no longer stops the table. A key taken away still stops while a change log exists, and a key column of another family stops.
- A column missing from one file, one page or one run of a file or REST table is empty, and with a change log never goes. A REST column absent from every row of a page no longer fails the run, and the files of a pattern may have different columns. Where the definition names the columns it is the catalog: a type under `columns` that changes to another family goes and comes back, a pin taken out of a CSV, Excel or JSON column goes back to `text` or `jsonb` the same way, and a column taken out of a REST table's `columns` leaves the mirror, all recorded `by = definition`. A Parquet column of another family than before stops with the hint to pin it, and the drop where a pin was taken out.
- A table without a change log stops at a column that is gone or of another family, as before, and the reason now says the way out (`ALTER TABLE ... DROP COLUMN ...`). So does a file or REST table without one at a mirror column missing from the data. A column a person added to the mirror, or dropped from the change log, is never dropped or written, also when the source brings its name: the run stops with `is not in the change log` and says to drop it, after copying its values. A type a person changed in the mirror to another family stops, and the reason says to drop the column.
- A column the change log keeps costs change-log rows: a `U` per row that had a value for a column that goes, one per row for a type of another family, a `D` and an `I` per row for a changed key (docs/target.md, with the shakedown's numbers). A `numeric(p,s)` a run widened to plain `numeric` reads without trailing zeros (docs/connectors.md).
- The history view is dropped and created again whenever a run does more than add columns, so a consumer's view on a history view stops a change to any column of it. The grants on it are given again in the same transaction, a granted column's under its new name after a rename, and one a grantee passed on by that grantee, where the worker's role may act as it (docs/target.md). A statement prepared on a mirror fails after its columns change, a new one, one that goes or a widened type, on every call until it is prepared again; a reader that lists the columns and then selects them reads the list again when one is gone.
- `columns__history` carries `_run` and `_op`, and for each version the run that ended it with that run's `by` and `note` (`_valid_to_run`, `_valid_to_by`, `_valid_to_note`), so that the queries of docs/target.md, also what a listener reads after a notification, need `SELECT` on that view alone, and list a column a person closed by hand. Who may read it sees the columns of every schema of the target, and the names of indexes, constraints and roles in the notes.
- `renamed` onto `_op`, `_run`, `_loaded_at`, `_valid_from` or `_valid_to` is refused by `apply`, and a run that meets such a name stops with `is a name of the change log or the history view` before anything else; no reason tells a person to rename a column of the change log's own. `_op cannot be freed` says to read the source through a view that names the column otherwise.
- A retired name the source has taken stops the run with `a later run keeps them under its own number, nothing is to be done`, and the next run whose name is free retires the column by itself. Before, the reason said to rename the change log's column, which cut the old values off and led into a second stop.
- A source that delivers a type of another family than before writes a row per row into the change log, once, on every affected table, at the first run of this version.
- docs/loading.md: the table of checks and "What a person does by hand" are rewritten. The recipes for a dropped column, a changed type, more digits and a changed key are gone for tables with a change log and stay for tables without one; every stop gives its reason and its way out.

Fixed:

- A table stuck on `is missing in the source` or `has changed its type` resolves with the first run of this version, if it has a change log; what that run changes is recorded `by = reader` and notified.
- A table stuck on a primary key other than the definition's resolves too: one a person changed by hand is put back (`by = hand`) and the history stays right, one the definition changed is taken with the history kept. The run tells the two by the definition of the table's last successful run or by the change log, and where neither tells it stops with the two comments on `_op` that settle it (docs/loading.md).
- A run refused `_rowvioli.columns` or `columns__log` says that the worker's role lacks a right there, which `rowvioli init` printed with the upgrade, and a target of version 3 is refused with `rowvioli init brings it to 4`. Stop every old worker before `init`: one forgotten writes a line several times a second and changes nothing (docs/operation.md). Two `init` at once, from init containers on several replicas, both end as on a ready target: the second waits for the first. A superuser's `init` gives the new objects the owner of `_rowvioli.runs`; another role is told that owner's name, and Ctrl+C that nothing was changed. Before, the second `init` failed with `column "program_version" of relation "runs" already exists`, a superuser's left objects a later `init` by the owner could not alter, and the others printed Postgres's bare message.
- A `numeric` no decimal holds is said to be `NaN` or `Infinity`, or a value of more than 38 digits before or after the point. A REST value not of its column's type says the way out, as the file connector's does.
- A line break or other control character in a name no longer cuts a reason: it is written `?`.
- `N % of the rows would be deleted` says the `max_delete_share` it exceeds, that the source table may have been replaced or emptied, and that `max_delete_share = 1.0` on the table lets one run through. A source table created anew with other columns and rows stopped with the share alone.
- A stop for a consumer's object names every object in the way of the run's changes, through the layers (a view on a view on the history view, a materialized view on a column that goes, every view, rule, trigger, policy, publication and generated column on a widened column), so that one round of work clears it. Before, it named those of the first change Postgres refused, and only one view for a widened type. A run that is stopped so never waits for a consumer's view it would drop with a column: a consumer reading that view while the run held the mirror had its query ended by Postgres as a deadlock (story 43); the catalogue names that view. Every object is named with its schema, also one in `public`. A key whose old column leaves it, stopped by a consumer's foreign key, names the foreign key, where it failed with `column "customer_no" is in a primary key`.
- A retired name longer than 63 bytes names every such column of the run in one reason, and its way out, the same shorter name in mirror, change log and history view, leads out in one step. Before, it named one column at a time, and renaming the change log's column alone led into a stop at the mirror's.
- A comment on `_op` edited into a key that is no list, a `from` that is no moment or a column the change log lacks stops with the reason of a lost comment and the text to put back, instead of Postgres's message.
- A column name longer than 63 bytes from a file or REST source fails the run before anything is written and names the column, and two names equal in their first 63 bytes name both. Before, the driver's message did.
- A reason no longer shows a value of the source: a value a type under `columns` does not take names the file, the column and the type instead of DuckDB's message with the value; a `numeric` that no decimal holds from the `postgres` connector names its column. A database's message, of the source or the target, through ADBC or ODBC, is shown only where its SQLSTATE says that it holds names alone (a lost connection, a refused login, a missing right, a full disk, an object in use and the like) or it is Postgres's own message of a violated constraint; every other is withheld, and the reason names its SQLSTATE, the function that raised it where the driver names one, the source table, and the server's log that has the message: `function guard() raised an error (SQLSTATE P0001) in the target; ...`, `a statement raised an error (SQLSTATE 22P02) in the source, reading public.orders; ...`. Before, a message raised under a consumer's code in any language (`raise exception 'bad row %', NEW` in a trigger, a function a source view calls), Postgres's own message of a value (`date field value out of range: 2000-13-01`, `relation "Anna" does not exist` of a cast to `regclass`) and an ODBC driver's in its own words (psqlODBC's `invalid input syntax for type integer: "…";`, SQL Server's `'…'`) reached the status, `_rowvioli.runs` and the lines.
- A run ended after `max_seconds` while it writes the change log's rows for a column that goes, replaces a mirror under another key or compares the rows for the proof of a rename names that step and says to raise `max_seconds` once, as a widening did. Before, the reason was `ended after max_seconds = N` alone.
- An unconstrained `numeric` far beyond 38 digits before the point fails the run with the reason of more than 38 digits. Before, Arrow's cast wrapped it without an error, and `1.5e400` arrived as `0` with the run `ok` (in 0.4.1 too).
- A table that was never tried is claimed before the tables that are overdue, and among those the most overdue first, as before. Before, a new table counted as hardly late and waited behind tables that stayed overdue: 34 of 50 new tables were still `new` after four minutes with `max_age = "1s"` (in 0.4.1 too).
- A pooler in transaction mode in front of the target is refused at the start of every command, idle or busy, with `a connection pooler in transaction mode is in front of the target; use session mode or connect directly`, before anything is claimed. Before, an idle one passed the check, and `run` and `work` failed with `bind message supplies 2 parameters, but prepared statement "" requires 0` or `relation "_stage" already exists` and left tables `loading` until the pooler restarted (in 0.4.1 too). A run process no longer makes the check: its worker has.
- A password that occurs in the driver's wrapper (`x`, `query`, `Failed`) no longer keeps the wrapper and the statement in the reason: the reason is cut first and scrubbed last. An error a connector raises while its rows are read is given as the connector raised it, so a name with a line break in it is no longer cut there, and a source's message read through the `postgres` connector loses `Execution error [PGRES_FATAL_ERROR]: ERROR:` before it.
- The counts of a run that drops a column are rows of the mirror: `~3` for three rows whose other columns changed. Before, they counted the change log's `U` rows, one for every row that had a value in the column (`~60`).
- `rowvioli run` whose own connection the target drops, as a restart does, ends with the line `connection to the target lost`. Before, its last line was Postgres's bare `FATAL:  terminating connection due to administrator command`.
- A run that adds a column never waits for the change log while it holds the mirror: it locks mirror, change log and history view first, without waiting, as for every change of columns, and a long reader makes it fail with `... stayed in use for 10 s, so its columns could not change` instead of `lock timeout`. Before, a consumer joining the history view with its mirror meanwhile had its query ended by Postgres as a deadlock (in 0.4.1 too).
- A consumer's table that inherits from a mirror keeps its rows. Before, a run read them as the mirror's, deleted them as `D` rows and counted them towards `max_delete_share` (in 0.4.1 too). The history view reads only the change log's own rows.
- A `timestamp` or `timestamptz` of `infinity` from the `postgres` connector, also in an array, fails the run with a reason that names the column and says to cast it in a view of the source; the driver cannot write it into the target. Before, the reason was `Error occurred writing COPY data:` (in 0.4.1 too). `-infinity` and a date's `infinity` load as before.
- A Parquet column of a struct or a map, also in a list, or of a list of lists loads as `jsonb`, as a nested value of a JSON file does. Before, the run failed with the driver's `Can't map Arrow type 'struct' to Postgres type`, naming no column (in 0.4.1 too).

## 0.4.1 (2026-11-23)

Fixed:

- A run whose target name `apply` changes while it loads, or whose table leaves the definition, fails and publishes nothing: `the target name changed to raw_erp.clients while this run loaded raw_erp.customers; nothing was published, the next run loads raw_erp.clients`. Before, it published into the old name, also when `apply` had given that name to another table, whose mirror then held the wrong rows with status `ok` (decision 53). It holds once every worker runs this version: a worker of 0.4.0 still publishes under a name it lost.
- A worker whose stderr fails once, on a full disk or a log stream that stalls, writes its lines again once the failure passes. Before, it stayed silent for good, and a later crash printed no traceback. A line that fails is lost (decision 52).

Changed:

- `rowvioli apply`, `apply --check` and `list` fail on a control character (C0, DEL, C1, U+2028, U+2029) in a source name, a source table, a key column, `target_schema` or `target_table`, and name the file, the setting and the name with the character as an escape such as `\x1b` (decision 39). A name already in a target keeps loading until the definition is applied again, which `apply` refuses until the name is changed. To leave it, give the table a clean `target_table`, apply, and drop the old tables by hand (docs/loading.md "What a person does by hand").
- `rowvioli status` (every column), the lines of `rowvioli apply` and every message a command stops with (a file or folder name in an error of `apply`, a connection key, a key file path, the refusal of a target) write a control character (escape, carriage return, DEL, C1) as `?`, as the lines of `work` do. A reason that quotes source data can no longer clear the terminal. What is stored and the JSON of `run` and `list` stay as they are.
- `rowvioli apply` accepts only ASCII digits in `max_age` and in `at`; an Arabic-Indic or full-width digit gets the usual message instead of the database's.
- A target address that does not start with `postgresql://` or `postgres://` says so (without printing the address) instead of `invalid connection option`. A target password with an unencoded `/` or `?` is refused before connecting, with the way to write it (`%2F`, `%3F`): such an address never worked, and the driver's message showed the password up to the `/`. A table that had a key and has none in the definition now fails with a reason that says so and names the ways out (put the key back, another `target_table`, or drop the change log and the mirror to load without a key), instead of `the key [] differs from the mirror's primary key`.

Added:

- Ctrl+C ends `work` and `run` with one line, `stopped by Ctrl+C, 2 runs ended`, instead of a traceback: the run processes are ended before the program exits with 130. The tables of the ended runs close as `worker lost`. SIGTERM keeps its meaning of letting the runs finish (decision 33). For this the run processes have a process group of their own: a signal sent to the worker's group (`timeout`, `kill -- -PGID`, `tini -g`) reaches the worker alone, and the runs end when the worker does. On Windows a run still gets Ctrl+C itself and may record it as its reason.
- `work` writes `✔ the target is reachable again after <seconds>s` once when an outage of the target ends, after the `⚠ the target is unreachable` line, so a log shows how long it lasted.

## 0.4.0 (2026-11-23)

Changed:

- The lines of `run` and `work` on stderr are the same at a terminal and in a log, and easier to read in both: date and time, a mark (`▶` started, `✔` ok, `✘` failed, `⚠` the target is unreachable), then a run's target table, `started`, `ok` or `failed`, its seconds and `+inserted ~updated -deleted` or the reason, in columns. `raw_erp.customers ok after 0.4s: 3 inserted, 0 updated, 0 deleted` is now `✔ raw_erp.customers            ok          0.4s  +3 ~0 -0`; a script that reads the old lines has to adapt. They are coloured by default, in a pipe, a file and a container log too, except when `NO_COLOR` is set and not empty, `TERM=dumb` or stderr is the systemd journal (decision 52).
- A control character in a target table name or in a reason (escape, newline, carriage return, DEL, C1) is written as `?` in the lines, so a name cannot clear the screen, set the window title or forge a line in the log (decision 52).

## 0.3.1 (2026-11-18)

Fixed:

- A NUL byte in a text value no longer fails the run with `invalid byte sequence for encoding "UTF8": 0x00`: it is removed while staging, for every connector. Text inside a list, a struct or a JSON value is not cleaned.

## 0.3.0 (2026-11-18)

Added:

- `rowvioli list` reads the source from the target where there is no `sources/` in the current directory and no `--definition`: it decrypts the stored connection with the worker key, so it runs on a worker's machine, which has the connector, the route to the source and no checkout. A new source is applied with an empty `tables` block, listed on a worker's machine and applied again. With `sources/` here or `--definition`, `list` works as before.

Fixed:

- `rowvioli run <source>` for a source applied with an empty `tables` block says ``erp has no tables; `rowvioli list erp` prints them``, and for a source no longer in the definition `erp is not in the definition any more`, instead of `erp is no source`.
- `rowvioli list` of a `file` source with a missing directory names the directory instead of `***`.
- `rowvioli list` of a source whose connection lacks a field says `the connection of source erp has no url` instead of `'url'`.

## 0.2.2 (2026-11-18)

Changed:

- `apply`, `apply --check` and `list` read the source files in the subfolders of the definition directory too; an error in one of them names it with its subfolder (`crm/crm.toml: ...`). A source file that was kept in a subfolder, a hidden one too, is therefore applied now: move it out of the directory to keep it disabled.

## 0.2.1 (2026-11-18)

Fixed:

- A password with a `[` written plainly in a URL of the definition no longer fails the run with `Invalid IPv6 URL`: the run goes on to connect, and the password is still scrubbed from every reason and error.

## 0.2.0 (2026-11-18)

Added:

- The README has a section "Try it in a minute": with Python and Docker, a CSV file and a throwaway Postgres, copy and paste give a first mirror and its history; a test runs the block.
- The README is short: what the program is, the start, "Try it in a minute", the guarantees and a paragraph per topic. The reference it held lives on pages under `docs/` (definition, loading, target, connections, commands, operation, connectors), word for word.
- The first mirror needs one variable, `ROWVIOLI_TARGET_URL`: `ROWVIOLI_KEY_FILE` falls back to `worker.key` in the current directory, and `apply` without a directory takes `sources`. The start is `key new`, `apply --init`, `work`, `status`.
- `run` and `work` stop at the start when the key file cannot be opened, and name the path and the reason. A missing one says to copy `worker.key` from where `rowvioli key new` was run; a key of the wrong pair fails each table with a reason that names both ways out. `apply` without `worker.pub` says that `rowvioli key new` creates it.
- Slips named: `apply` without a `sources` directory names where it looked; `run <name>` where the name is no source says so and suggests the source; a target address with a second `@` fails before connecting; `rows` that is no field name fails the run.
- The `rest` connector reads rows from a field of a wrapped answer: `rows = "data"` or `rows = "result.items"`.
- The `file` connector reads JSON files (`.json`, `.jsonl`, `.ndjson`, every column as `jsonb`) and patterns such as `orders_*.csv`, which read every matching file as one table; a file that lands later arrives on the next run. A pattern reads any number of files, 50 at a time (measured with 5000).
- `rowvioli key new --help` says what it writes. The `odbc` connector without the driver manager says to install `unixodbc`.

Changed (a working set-up can notice these):

- Update every worker before applying new tables. A new mirror has `numeric(p,s)` where the source has it (up to 38 digits, with a scale from 0 to the precision), so `137.00` stays `137.00`; DuckDB's `decimal(10,2)` arrives as `numeric(10,2)`. A worker of 0.1.0 fails on such a mirror (`column price has changed its type from numeric(10,2) to numeric`); going back to 0.1.0 needs `ALTER TABLE ... ALTER price TYPE numeric` on those columns, in the mirror and its change log.
- A mirror made by 0.1.0 keeps loading with nothing to do and keeps `numeric`, so a row loaded before shows `137` and one loaded after `5.50`; they compare equal. A target table with `numeric(10,2)` where the source has `numeric` loads the values that fit and fails on the first that does not, naming the column, the type and the value. "What a person does by hand" in `docs/loading.md` widens such a column.
- An option that a `postgres`, `odbc` or `rest` connector does not know (`incremental = "updated"` on `postgres`) fails the run and names the option and those the connector knows, whether it is set on the table or on the source; set on the source, it fails every table of it.
- A `type` one letter from `postgres`, `file`, `odbc` or `rest`, and `postgresql`, fails `apply` with a hint (`did you mean file?`) unless a connector of that name is installed where `apply` runs. A setting of three letters or fewer one letter from `key`, `log` or `at` (`kye`) fails like the longer ones, and two neighbouring letters swapped count as one edit (`fiel`, `max_aeg`).
- A source that delivers zero rows publishes when the table says `max_delete_share = 1.0`; without it the run still fails, and the reason says so.
- The `path` of a `file` connection stays readable in a reason; every other value of a connection is still hidden.
- A CSV skips no line before its header unless `skip` says so. A CSV with lines before its header needs `skip`.
- A CSV that splits into a single column fails unless `sep` is given. A CSV of one column needs `sep`.

Lower dependency floors, each tried with the whole suite (CI now runs it on the floors): `pyarrow>=19` (was 26), `pynacl>=1.5` (was 1.6), `duckdb>=1.5` (was 2), `arrow-odbc>=9.3.0` (was 10.7). `adbc-driver-postgresql>=1.13` and `httpx>=0.28` stay.

Fixed:

- The next run of a table closes the row of a run that died: `failed`, reason `worker lost`, with a finish time, instead of `running` for ever.
- An empty file fails and says that it is empty.
- A ragged CSV fails instead of losing its header or arriving as one column.
- A file name with `[`, `*` or `?` is no longer expanded a second time by DuckDB, which could read another file than the one named.
- A `numeric` with a negative scale, such as `numeric(5,-2)` (Postgres 15 and later), loads as `numeric` instead of failing with `Rescaling Decimal value would cause data loss`.
- A table whose target schema or table changes is new again: due at the next run, without the age, attempts and reason of the old name, since no mirror exists under the new name.
- A run whose connection to the target is lost ends within seconds of its worker reaching the target again, with `connection to the target lost`; before, it read its source to the end, and the retry could read it at the same time.
- `work` and `run` say an error of the target in one line, without the query that was sent.
- A run ended because its target connection was lost, or after `max_seconds`, keeps that reason in `runs` and the status, also when another worker's claim found it dead first; before, both could show `worker lost`.

## 0.1.0 (2026-11-17)

First release.

- Commands: `init`, `key new`, `list`, `apply` with `--check` and `--init`, `run`, `work`, `status`.
- Connectors: `postgres`, `file` (CSV, Excel, Parquet), `odbc`, `rest`.
- Core: table lock, staging, checks, diff, publishing, mirror and change log, encrypted connections, the status view, retry.
- History: the change log `<table>__log` and the view `<table>__history` over it.
- Per table: target names (`target_table`, `target_schema`), load times (`at` with `timezone`).
- Limits: per worker, per source, per target.

There is no migration of the `_rowvioli` schema between versions yet. The program refuses a target with another schema version.

Known limits and open points are in `docs/open-points.md`.
