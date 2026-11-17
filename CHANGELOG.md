# Changelog

## Unreleased

Added:

- The first mirror needs one variable, `ROWVIOLI_TARGET_URL`: `ROWVIOLI_KEY_FILE` falls back to `worker.key` in the current directory, and `apply` without a directory takes `sources`. The start is `key new`, `apply --init`, `work`, `status`.
- `run` and `work` stop at the start when the key file does not exist, and name its path and `rowvioli key new`. `apply` without `worker.pub` says that `rowvioli key new` creates it.
- A `type` one letter from `file`, `odbc` or `rest`, or two from `postgres`, fails `apply` with a hint (`did you mean postgres?`). A connector of one's own cannot be named so close to a built-in one.
- The `rest` connector reads rows from a field of a wrapped answer: `rows = "data"` or `rows = "result.items"`.
- The `file` connector reads JSON files (`.json`, `.jsonl`, `.ndjson`, every column as `jsonb`) and patterns such as `orders_*.csv`, which read every matching file as one table; a file that lands later arrives on the next run.
- `rowvioli key new --help` says what it writes. The `odbc` connector without the driver manager says to install `unixodbc`.

Changed (a working set-up can notice these; both fail the run and name the option):

- A CSV skips no line before its header unless `skip` says so. A CSV with lines before its header needs `skip`.
- A CSV that splits into a single column fails unless `sep` is given. A CSV of one column needs `sep`.

Fixed:

- A ragged CSV fails instead of losing its header or arriving as one column.
- A file name with `[`, `*` or `?` is no longer expanded a second time by DuckDB, which could read another file than the one named.
- A table whose target schema or table changes is due at the next run, since no mirror exists under the new name.

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
