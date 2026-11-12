# 03: The `odbc` connector

**Blocked by:** None (can start immediately)

**Status:** resolved

**Model:** Opus

Spec: `.scratch/connectors/spec.md`. Prior art: `src/rowvioli/connectors/postgres.py`, `tests/test_run.py`, `tests/test_list.py`, `tests/test_secrets.py`, `.github/workflows/tests.yml`. Tests: the existing seam (`tests/conftest.py`), real processes, no import of the program.

## What to build

Spec stories 11 to 22 and the implementation decisions under "The `odbc` connector".

- `src/rowvioli/connectors/odbc.py` with `read` and `tables`, registered in the entry point group; the extra `odbc` with arrow-odbc; the extra joins the development dependencies.
- Check the licence of arrow-odbc on PyPI and correct its row in `docs/package.md` if needed.
- The password inside the connection string is scrubbed from reasons and lines, not only the string as a whole; extend the existing extraction of connection values if it is not.
- The table name check runs before any query is sent.
- The tests run against PostgreSQL through psqlODBC, driver manager and driver in a container, nothing installed on the machine (spec "Further Notes", last bullet). They skip with a clear message where no driver manager can be had.
- A type conversion only if the test shows one is needed; then note it in this ticket's comments for ticket 04.

## Acceptance criteria

- [ ] Spec "What is tested" 1 to 4.
- [ ] The suite passes on a machine without ODBC driver manager or driver (the `odbc` tests skip, nothing else breaks).
- [ ] No driver, SDK or vendor file in the repo, the package or the example Dockerfile.
- [ ] No documents except the row in `docs/package.md` (ticket 04).

## Comments

**2026-11-12, implementer (con-03):**

- **Licence:** arrow-odbc 10.7.0 is MIT on PyPI (`license_expression`); the row in `docs/package.md` was right and is unchanged.
- **Test source changed by the owner:** the odbc tests run against the harness's PostgreSQL source through the open psqlODBC driver (`odbc-postgresql`, LGPL, used by the tests only, no dependency of the package, no row in the table), not against SQL Server. No Microsoft image, driver or `ACCEPT_EULA` anywhere. **SQL Server and Informix are untested.** What an operator should look at first there: the target types of decimals, dates and timestamps (SQL Server's `datetime2` and `datetimeoffset`, Informix `DATETIME` and `MONEY`), unbounded text columns (`varchar(max)`: arrow-odbc needs a size limit, which the connector does not set), and whether the driver quotes the connection string back in its errors (the password is scrubbed either way, see below).
- **Types:** no conversion needed. Through psqlODBC `int`, `text`, `numeric(10,2)`, `date`, `timestamp` and nulls arrive as `integer`, `text`, `numeric`, `date`, `timestamp without time zone` with equal values. No mapping written, README "Types" needs nothing new.
- **Scrubbing:** `connection_values` (`src/rowvioli/load.py`) now also extracts the password of any ODBC connection string: `PWD=` or `Password=`, any case, spaces around `=`, plain or in braces (`{se;cret}` with `}}` for `}`), as written and unbraced. Tested with the `testing` connector quoting only the password (`tests/test_secrets.py`), so it holds whatever the driver says.
- **Built differently from the spec:**
  - A shipped connector whose import fails (`ImportError`, or `OSError` when arrow-odbc finds no driver manager to load) now fails as "connector "odbc" is not installed on worker …", followed by the import error (`src/rowvioli/contract.py`). Without this, the entry point exists in the core and a missing extra would have failed with a bare import message.
  - Story 18 (driver not installed): the run fails with the driver manager's message; the worker is named in `_rowvioli.runs` like every run, but not inside the reason, since the connector does not know the worker. Not tested.
  - Story 17 (no `INFORMATION_SCHEMA`): `list` fails with "the source has no INFORMATION_SCHEMA to list tables from, write the tables block by hand (driver message)". Untested, as no such free source is in the harness.
  - `tables` skips the schemas `INFORMATION_SCHEMA`, `pg_catalog` and `sys`, since PostgreSQL lists its catalogs in `INFORMATION_SCHEMA.TABLES`.
  - Table names: Unicode letters count as letters (`\w`), so `dbo.Kunden_Ä` passes; quotes, semicolons, spaces do not.
  - Spec test 4 ("no query sent") uses an unreachable server: a refusal naming the rule shows no connection was tried.
- **How the odbc tests run:** they need an ODBC driver manager with the driver `PostgreSQL Unicode` (`unixodbc` and `odbc-postgresql` on Debian/Ubuntu). In CI the workflow installs both on the runner and `uv run pytest` runs everything. On a machine without them (the owner's Mac) the odbc tests skip with a sentence naming `tests/odbc/run.sh`, which builds a small image (uv, Docker CLI, unixODBC, psqlODBC; `tests/odbc/Dockerfile`) and runs `tests/test_odbc.py` in it with the Docker socket mounted; the Postgres containers are reached through `host.docker.internal` (Docker Desktop), set by `ROWVIOLI_TEST_HOST`, which `tests/conftest.py` reads. Nothing is installed on the host. On such a host the test for a missing driver manager runs instead and checks the "not installed" wording.

Resolved on branch `connectors`, from con-03 (54c75fe). Review fixes: 8ce4756.

On 2026-11-12 the owner changed the testing during implementation: a free source only (PostgreSQL through psqlODBC, in a container), no SQL Server, nothing installed locally. See the last bullets under "Further Notes" in `spec.md`.
