# Changelog

## Unreleased

Fixed:

- A run whose target name `apply` changes while it loads, or whose table leaves the definition, fails and publishes nothing: `the target name changed to raw_erp.clients while this run loaded raw_erp.customers; nothing was published, the next run loads raw_erp.clients`. Before, it published into the old name, also when `apply` had given that name to another table, whose mirror then held the wrong rows with status `ok` (decision 53).
- A worker whose stderr fails once, on a full disk or a log stream that stalls, writes its lines again once the failure passes. Before, it stayed silent for good, and a later crash printed no traceback. A line that fails is lost (decision 52).

Changed:

- `rowvioli apply`, `apply --check` and `list` fail on a control character (C0, DEL, C1, U+2028, U+2029) in a source name, a source table, a key column, `target_schema` or `target_table`, and name the file, the setting and the name with the character as an escape such as `\x1b` (decision 39). A name already in a target keeps loading.
- `rowvioli status` and the error messages of `rowvioli list` and of an unreachable or refusing target write a control character (escape, carriage return, DEL, C1) as `?`, as the lines of `work` do. A reason that quotes source data can no longer clear the terminal. What is stored and the JSON of `run` and `list` stay as they are.
- `rowvioli apply` accepts only ASCII digits in `max_age` and in `at`; an Arabic-Indic or full-width digit gets the usual message instead of the database's.
- A target address that does not start with `postgresql://` or `postgres://` says so (without printing the address) instead of `invalid connection option`. A table that had a key and has none in the definition now fails with a reason that says so and names both ways out, instead of `the key [] differs from the mirror's primary key`.

Added:

- Ctrl+C ends `work` and `run` with one line, `stopped by Ctrl+C, 2 runs ended`, instead of a traceback: the run processes are ended before the program exits with 130. The tables of the ended runs close as `worker lost`. SIGTERM keeps its meaning of letting the runs finish (decision 33).
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
