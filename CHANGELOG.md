# Changelog

## 0.1.0

First release.

- Commands: `init`, `key new`, `list`, `apply` with `--check`, `run`, `work`, `status`.
- Connectors: `postgres`, `file` (CSV, Excel, Parquet), `odbc`, `rest`.
- Core: table lock, staging, checks, diff, publishing, mirror and change log, encrypted connections, the status view, retry.
- Limits: per worker, per source, per target.

There is no migration of the `_rowvioli` schema between versions yet. The program refuses a target with another schema version.

Known limits and open points are in `docs/open-points.md`.
