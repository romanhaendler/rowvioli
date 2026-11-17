# Changelog

## Unreleased

Added:

- The README has a section "Try it in a minute": with Python and Docker, a CSV file and a throwaway Postgres, copy and paste give a first mirror and its history; a test runs the block.
- The first mirror needs one variable, `ROWVIOLI_TARGET_URL`: `ROWVIOLI_KEY_FILE` falls back to `worker.key` in the current directory, and `apply` without a directory takes `sources`. The start is `key new`, `apply --init`, `work`, `status`.
- `run` and `work` stop at the start when the key file cannot be opened, and name the path and the reason. A missing one says to copy `worker.key` from where `rowvioli key new` was run; a key of the wrong pair fails each table with a reason that names both ways out. `apply` without `worker.pub` says that `rowvioli key new` creates it.
- Slips named: `apply` without a `sources` directory names where it looked; `run <name>` where the name is no source says so and suggests the source; a target address with a second `@` fails before connecting; `rows` that is no field name fails the run.
- The `rest` connector reads rows from a field of a wrapped answer: `rows = "data"` or `rows = "result.items"`.
- The `file` connector reads JSON files (`.json`, `.jsonl`, `.ndjson`, every column as `jsonb`) and patterns such as `orders_*.csv`, which read every matching file as one table; a file that lands later arrives on the next run. A pattern reads any number of files, 50 at a time (measured with 5000).
- `rowvioli key new --help` says what it writes. The `odbc` connector without the driver manager says to install `unixodbc`.

Changed (a working set-up can notice these):

- Update every worker before applying new tables. A new mirror has `numeric(p,s)` where the source has it (up to 38 digits, with a scale from 0 to the precision), so `137.00` stays `137.00`; DuckDB's `decimal(10,2)` arrives as `numeric(10,2)`. A worker of 0.1.0 fails on such a mirror (`column price has changed its type from numeric(10,2) to numeric`); going back to 0.1.0 needs `ALTER TABLE ... ALTER price TYPE numeric` on those columns, in the mirror and its change log.
- A mirror made by 0.1.0 keeps loading with nothing to do and keeps `numeric`, so a row loaded before shows `137` and one loaded after `5.50`; they compare equal. A target table with `numeric(10,2)` where the source has `numeric` loads the values that fit and fails on the first that does not, naming the column, the type and the value. The README's "What a person does by hand" widens such a column.
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
