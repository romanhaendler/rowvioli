# Package and first version

The package as released in version 0.1.0. The specs under `.scratch/` call the two steps of building it 0.1 and 0.2; both are in release 0.1.0.

## What the package is

- **A command-line program, distributed through PyPI** under the MIT licence. Installed with `uv tool install rowvioli` on a worker, or as a dependency of the repo that holds the definition.
- **The only public Python interface is the connector contract**: the function `read`, and optionally `tables` for `rowvioli list`. The first version promises no API for loading from Python code.
- **Python 3.11 or newer**, because TOML is then read without an extra package.
- **No official Docker image.** The repo carries an example Dockerfile into which users put the vendor drivers themselves (see decision 16).

## What goes into 0.1.0

| Part | In 0.1.0 | Later |
|---|---|---|
| Commands | `init`, `key new`, `list`, `apply` with `--check` and `--init`, `run`, `work`, `status` | `request` as a shortcut for setting `requested_at` |
| Connectors | `postgres`, `file` (CSV, Excel, Parquet), `odbc`, `rest` | JSON files in `file` |
| Core | table lock, staging, checks, diff, publishing, mirror and change log, encrypted connections, the status view, retry | reading only rows from a timestamp on, patterns for table names |
| Limits | per worker, per source, per target | workers that serve only some sources |

Two points:

- **`work` is part of the package.** It is the loop of `run` without the end. Several workers on several machines need nothing more.
- **`odbc` and `rest` are part of it.** `odbc` is tested in CI against PostgreSQL through psqlODBC, a free source; SQL Server and Informix are untested. `rest` is tested against an HTTP server inside the test. Run the odbc tests on a machine without a driver manager with `tests/odbc/run.sh`.

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

## In short

`run` and `work` are the same loop in `work.py`. `run` ends when nothing is due any more.

`init` creates the schema `_rowvioli` and writes a schema version into it. The program refuses to start if the version does not match.

The first screen of the README shows the whole usage: one source file, the target's address, four commands and the status view. Whatever a user needs a drawing for to understand is cut or hidden.

## When the package is done

- The quickstart runs through with one `docker compose up`.
- Tests prove the guarantees:
  - a concurrent reader never sees an empty or half-loaded table,
  - a run killed at any step leaves the target unchanged and the table is loaded again after the pause,
  - the limits per source and per target hold,
  - each check fails the run and leaves the target unchanged,
  - `apply` twice gives the same state and never changes what the workers experienced.
- The benchmark script reproduces the numbers in `docs/measurements.md`.

## Releasing

A version is released by raising `version` in `pyproject.toml` and adding its entry to `CHANGELOG.md`. The push to `main` that carries it runs the tests, builds, publishes to PyPI through trusted publishing in the environment `pypi` and sets the tag `v<version>`. A push that does not raise the version publishes nothing. A version on PyPI can never be replaced. A mistake is fixed by the next version.

## Name

The project is called `rowvioli`: ravioli made of rows. It loads in small parcels. The owner searched the trademark registers (DPMAregister, EUIPO TMview, USPTO) on 2026-11-17 and found no conflict.
