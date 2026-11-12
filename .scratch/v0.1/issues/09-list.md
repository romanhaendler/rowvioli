# 09: `rowvioli list`

**Blocked by:** 08

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli list <source>` reads the definition and the environment, opens the source's connection, calls the connector's `tables` and prints TOML ready to paste into the source's `tables` block. `postgres` lists its tables with their primary keys; `file` lists its files without keys. A connector without `tables` fails with a clear message.

- [x] `list` for `postgres` and `file` prints TOML that, pasted into a definition, applies and loads (spec test 17)
- [x] A connector without `tables` fails with a clear message

## Comments

- Owner's decision built here: a file's target table is its name without the extension, in lower case (`customers.csv` → `customers`). Spec, README and GLOSSARY state it. `tests/test_file.py` now names its files `customers_csv.csv` and so on, so the three formats stay apart.
- `list` reads the definition from `sources/` in the current directory, or from `--definition <dir>` (README command table). It prints only the lines for the `tables` block, not the `[<source>.tables]` header.
- `list` fills in the placeholders of the whole definition, so every source's variables must be set, as for `apply`.
- `postgres` lists base and partitioned tables, not partitions, views or system schemas. Two tables of the same name in different schemas give one target table, so `apply` refuses the pasted list until one is removed.
