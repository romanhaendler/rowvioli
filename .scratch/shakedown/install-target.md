# Shakedown 2026-11-15: install and target

Status: needs-triage (taken up in `spec.md`)

From H1. Wheel on Python 3.11 (`python:3.11-slim`) and 3.14; targets Postgres 15 and 18; pgbouncer.
Not covered: Postgres 17, ODBC and REST in use.

## Findings

1. **[Wrong] Behind a transaction-mode pooler, runs share TEMP tables and locks:** `_stage already exists`,
   tables stuck in `loading`, two advisory locks never released, one table `ok`. documented: README:555 and
   :768 forbid it; nothing detects it. Idea: compare `pg_backend_pid()` across two statements at connect and
   fail with "pooler in transaction mode, use session mode".
2. ✓ **[Misfit] A worker needs `CREATE` on the database even when its schema exists**, because `load.py:185`
   always runs `CREATE SCHEMA IF NOT EXISTS`. Idea: skip it when the schema exists.
3. ✓ **[Misfit] An error from the target masks the user name** (`for user "***"`): `cli.py:39` scrubs every
   value of the URL, which hides the likeliest typo. Same root as `security.md` 3.
4. **[Misfit] The README's rights table gives no SQL.** The grants (`USAGE` on `_rowvioli` for workers and for
   `status`, `CREATE` on the database for `init` and workers) were found by trial. Idea: the GRANT lines per role.
5. **[Misfit] The `odbc` extra installs on a slim image but cannot import** (`libodbc.so.2` missing).
   documented: `examples/Dockerfile:7`, as a comment. Idea: a hint in the connector's error.

## What held up

- Install and every `--help` on 3.11 and 3.14; the quickstart on Postgres 15 and 18, as superuser and as a plain role.
- Session-mode pgbouncer works. Rights failures name the cause; exit codes are right.
