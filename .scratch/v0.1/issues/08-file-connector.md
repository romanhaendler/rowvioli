# 08: The `file` connector

**Blocked by:** 03

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `type = "file"` (extra `file`, DuckDB) expects `path`, a directory; a table is a file name relative to it. CSV, Excel and Parquet are read by extension and delivered as Arrow batches. Parquet keeps its own types; CSV and Excel deliver every column as text unless the option `columns` names types. Other options such as a separator or a sheet name are passed to DuckDB. A missing file fails the run with a reason. Registered through the entry point group like `postgres`. The optional `tables(connection)` lists the files in the directory, without keys (used by 09).

- [x] A CSV, an Excel and a Parquet file are mirrored (spec test 15)
- [x] CSV and Excel arrive as text unless `columns` names types; a separator option is honoured; a missing file fails with a reason

## Comments

- **Open point for the owner: file names as target tables.** The spec's rule "the target table is the last part of the source table's name" turns `customers.csv` into the target table `csv`. Two CSV files in one source therefore collide in `apply`. The tests use one file per extension to stay within the rule. Not changed here because it needs a decision (for example: for a file, the last part is the name without its extension). It also affects 09 (`list` prints file names).
- `columns` names DuckDB types (`integer`, `decimal(10,2)`). A type is checked against a type-name pattern before it is written into the query; option names must be identifiers and option values are bound as parameters.
- Excel needs DuckDB's `excel` extension, which DuckDB downloads on first use. A worker without internet cannot read Excel unless the extension is installed beforehand.
- `tables(connection)` returns `{file name: None}` for every `.csv`, `.xlsx` and `.parquet` file in the directory (`None` = no key); 09 decides how it is printed. Not tested through the seam until `list` exists.
- The dev dependency group now includes `rowvioli[file]`, so `uv sync` installs DuckDB for the tests.
- `decimal(10,2)` from `columns` arrives in the target as plain `numeric`, as the README's "Types" already says for the driver.
