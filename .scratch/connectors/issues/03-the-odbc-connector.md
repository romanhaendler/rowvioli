# 03: The `odbc` connector

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

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
