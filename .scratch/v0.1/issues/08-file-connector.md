# 08: The `file` connector

**Blocked by:** 03

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `type = "file"` (extra `file`, DuckDB) expects `path`, a directory; a table is a file name relative to it. CSV, Excel and Parquet are read by extension and delivered as Arrow batches. Parquet keeps its own types; CSV and Excel deliver every column as text unless the option `columns` names types. Other options such as a separator or a sheet name are passed to DuckDB. A missing file fails the run with a reason. Registered through the entry point group like `postgres`. The optional `tables(connection)` lists the files in the directory, without keys (used by 09).

- [ ] A CSV, an Excel and a Parquet file are mirrored (spec test 15)
- [ ] CSV and Excel arrive as text unless `columns` names types; a separator option is honoured; a missing file fails with a reason
