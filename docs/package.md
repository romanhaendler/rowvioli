# Package and first version

A proposal. Nothing here is built.

## What the package is

- **A command-line program, distributed through PyPI** under the MIT licence. Installed with `uv tool install rowvioli` on a worker, or as a dependency of the repo that holds the definition.
- **The only public Python interface is the connector contract**: the function `read`, and optionally `tables` for `rowvioli list`. The first version promises no API for loading from Python code.
- **Python 3.11 or newer**, because TOML is then read without an extra package.
- **No official Docker image.** The repo carries an example Dockerfile into which users put the vendor drivers themselves (see decision 16).

## What goes into 0.1

| Part | In 0.1 | Later |
|---|---|---|
| Commands | `init`, `key new`, `list`, `apply` with `--check`, `run`, `work` | `request` as a shortcut for setting `requested_at` |
| Connectors | `postgres`, `file` (CSV, Excel, Parquet) | `odbc`, `rest`, entry points for outside packages |
| Core | table lock, staging, checks, diff, publishing, mirror and change log, encrypted connections, the status view, retry | reading only rows from a timestamp on, patterns for table names |
| Limits | per worker, per source, per target | workers that serve only some sources |

Two points:

- **`work` is part of 0.1.** It is the loop of `run` without the end. Several workers on several machines need nothing more.
- **ODBC comes in 0.2.** The first two connectors can be tested in CI without vendor drivers. MSSQL is next, with a SQL Server container in CI. Informix cannot be tested without the IBM driver.

## Modularity

| Way | Set-up | In the definition |
|---|---|---|
| Shipped connector | `pip install rowvioli[odbc]` | `type = "odbc"` |
| Separate package | `pip install rowvioli-sap` | `type = "sap"` |

- **Shipped means: code in the core package, dependency optional.** The code of a connector is small. The weight is in DuckDB or arrow-odbc. Whoever loads only from Postgres installs neither.
- **Separate packages register through an entry point** in the group `rowvioli.connectors`. The program looks up installed connectors at start and finds them under their `type`. The shipped ones use the same mechanism.
- **No connector as a file next to the definition.** A worker has no checkout (decision 27).
- **No separate packages for the shipped connectors at first.** The mechanism allows splitting them off later without a change for users.

## Dependencies

| Package | Needed for | Licence |
|---|---|---|
| `pyarrow` | core | Apache-2.0 |
| `adbc-driver-postgresql` | core, `postgres` connector | Apache-2.0 |
| `pynacl` | core, encrypting connections | Apache-2.0 |
| `duckdb` | extra `file` | MIT |
| `arrow-odbc` | extra `odbc` | MIT |
| `httpx` | extra `rest` | BSD-3-Clause |

All are compatible with an MIT project. The core does everything on the control connection through ADBC: advisory lock, TEMP tables, COPY and the publishing transaction. Experiment 8 played a complete run through it, so no second Postgres driver is needed (decision 28).

## Repo layout

```
rowvioli/
  src/rowvioli/
    cli.py              commands, JSON answer, exit code
    definition.py       read and check the source files, fill in placeholders
    apply.py            write the definition into the target
    seal.py             encrypt and decrypt connections
    target.py           control connection: keepalive, lock, COPY, SQL
    load.py             one run: staging, checks, diff, publishing
    work.py             the loop: look for due tables, start a process per run
    contract.py         connector contract
    connectors/
      postgres.py
      file.py
    sql/                schema with the status view, claim, diff
  tests/                against a real Postgres
  bench/                reproduces the measurements
  examples/
    quickstart/         docker compose: source, target, one source file
    definition/         template for the repo that holds the definition
    Dockerfile
  docs/
  README.md
  GLOSSARY.md
  LICENSE               MIT
  pyproject.toml
  .github/workflows/    tests, publishing to PyPI
```

`run` and `work` are the same loop in `work.py`. `run` ends when nothing is due any more.

`init` creates the schema `_rowvioli` and writes a schema version into it. The program refuses to start if the version does not match.

The first screen of the README shows the whole usage: one source file, two commands and the status view. Whatever a user needs a drawing for to understand is cut or hidden.

## When 0.1 is done

- The quickstart runs through with one `docker compose up`.
- Tests prove the guarantees:
  - a concurrent reader never sees an empty or half-loaded table,
  - a run killed at any step leaves the target unchanged and the table is loaded again after the pause,
  - the limits per source and per target hold,
  - each check in step 4 fails the run and leaves the target unchanged,
  - `apply` twice gives the same state and never changes what the workers experienced.
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
