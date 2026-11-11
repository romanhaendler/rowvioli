# Package and first version

A proposal. Nothing here is built.

## What the package is

- **A command-line program, distributed through PyPI** under the MIT licence. Installed with `uv tool install rowvioli`, or as a dependency of the jobs repo.
- **The only public Python interface is the connector contract**: the functions `tables` and `read` and the type `Table`. The first version promises no API for loading from Python code.
- **Python 3.11 or newer**, because TOML is then read without an extra package.
- **No official Docker image.** The repo carries an example Dockerfile into which users put the vendor drivers themselves (see decision 16).

## What goes into 0.1

| Part | In 0.1 | Later |
|---|---|---|
| Commands | `init`, `check`, `run`, `key new`, `secret set` | `work`, `submit`, `secret rekey` |
| Connectors | `postgres`, `file` (CSV, Excel, Parquet) | `odbc`, `rest`, `python`, entry points for outside packages |
| Core | table lock, staging, checks, diff, publishing, mirror and change log, secret store | reading only rows from a timestamp on |
| Parallelism | several tables in one process, limit per source | several worker machines |
| Dead runs | detect and retry | |

Two points:

- **The schema for orders and waiting runs is there from the start.** `run` already uses the claim function internally. `work` and `submit` are then two more commands in 0.2, with no rebuild and no migration.
- **ODBC comes in 0.2.** The first two connectors can be tested in CI without vendor drivers. MSSQL is next, with a SQL Server container in CI. Informix cannot be tested without the IBM driver.

## Modularity

| Way | Set-up | In the source file |
|---|---|---|
| Shipped connector | `pip install rowvioli[odbc]` | `type = "odbc"` |
| Separate package | `pip install rowvioli-sap` | `type = "sap"` |
| File in the jobs repo | nothing | `type = "python"`, `module = "connectors.weather"` |

- **Shipped means: code in the core package, dependency optional.** The code of a connector is small. The weight is in DuckDB or arrow-odbc. Whoever loads only from Postgres installs neither.
- **Separate packages register through an entry point** in the group `rowvioli.connectors`. The program looks up installed connectors at start and finds them under their `type`. The shipped ones use the same mechanism.
- **No separate packages for the shipped connectors at first.** The mechanism allows splitting them off later without a change for users.

## Dependencies

| Package | Needed for | Licence |
|---|---|---|
| `pyarrow` | core | Apache-2.0 |
| `adbc-driver-postgresql` | core, `postgres` connector | Apache-2.0 |
| `pynacl` | core, secret store | Apache-2.0 |
| `duckdb` | extra `file` | MIT |
| `arrow-odbc` | extra `odbc` | MIT |
| `httpx` | extra `rest` | BSD-3-Clause |

All are compatible with an MIT project. Whether the core can do everything through ADBC alone (advisory locks, transactions, COPY) or needs a second Postgres driver is open. `data-extractor` used ADBC for the data path and found that two threads must never share a connection.

## Repo layout

```
rowvioli/
  src/rowvioli/
    cli.py
    run.py              the pipe and publishing
    contract.py         connector contract
    connectors/
      postgres.py
      file.py
    sql/                schema, claim, diff
  tests/                against a real Postgres
  bench/                reproduces the measurements
  examples/
    quickstart/         docker compose: source, target, one source file
    etl-jobs/           template for the jobs repo
    Dockerfile
  docs/
  README.md
  GLOSSARY.md
  LICENSE               MIT
  pyproject.toml
  .github/workflows/    tests, publishing to PyPI
```

`init` creates the schema `_rowvioli` and writes a schema version into it. The program refuses to start if the version does not match.

## When 0.1 is done

- The quickstart runs through with one `docker compose up`.
- Tests prove the guarantees:
  - a concurrent reader never sees an empty or half-loaded table,
  - a run killed at any step leaves the target unchanged and is retried,
  - the per-source limit holds,
  - each check in step 4 fails the run and leaves the target unchanged.
- The benchmark script reproduces the numbers in `docs/measurements.md`.

## Name

The project is called `rowvioli`: ravioli made of rows. It loads in small parcels.

Checked on 2026-11-11, all free:

| Where | Result |
|---|---|
| PyPI project `rowvioli` | free |
| Domains `rowvioli.com`, `.de`, `.io`, `.dev` | not registered (`.com` and `.de` confirmed by whois) |
| GitHub repositories with the name | none |
| GitHub account `rowvioli` | free |
| Web search for a product of that name | no hits (US results only) |

**Not checked: trademarks.** None of the above says anything about them. Before publishing, the name needs a search in the trademark registers (DPMAregister, EUIPO TMview, USPTO) by the owner.

None of these names is reserved yet. Registering the PyPI project, the GitHub account and a domain is the owner's step.
