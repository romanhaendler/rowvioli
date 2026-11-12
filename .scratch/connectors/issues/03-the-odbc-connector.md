# 03: The `odbc` connector

**Blocked by:** None for the code. The owner accepts Microsoft's terms before a SQL Server container or driver is used (spec "Further Notes").

**Status:** ready-for-agent

**Model:** Opus

Spec: `.scratch/connectors/spec.md`. Prior art: `src/rowvioli/connectors/postgres.py`, `tests/test_run.py`, `tests/test_list.py`, `tests/test_secrets.py`, `.github/workflows/tests.yml`. Tests: the existing seam (`tests/conftest.py`), real processes, no import of the program.

## What to build

Spec stories 11 to 22 and the implementation decisions under "The `odbc` connector".

- `src/rowvioli/connectors/odbc.py` with `read` and `tables`, registered in the entry point group; the extra `odbc` with arrow-odbc; the extra joins the development dependencies.
- Check the licence of arrow-odbc on PyPI and correct its row in `docs/package.md` if needed.
- The password inside the connection string is scrubbed from reasons and lines, not only the string as a whole; extend the existing extraction of connection values if it is not.
- The table name check runs before any query is sent.
- The tests run against a SQL Server container and skip with a clear message where the SQL Server ODBC driver (or the container) cannot be had; the workflow installs the driver where the runner lacks it. Check the free disk before the image is pulled; containers and volumes are removed after the session.
- A type conversion only if the test against SQL Server shows one is needed; then note it in this ticket's comments for ticket 04.

## Acceptance criteria

- [ ] Spec "What is tested" 1 to 4.
- [ ] The suite passes on a machine without ODBC driver manager or driver (the `odbc` tests skip, nothing else breaks).
- [ ] No driver, SDK or vendor file in the repo, the package or the example Dockerfile.
- [ ] No documents except the row in `docs/package.md` (ticket 04).

## Comments
