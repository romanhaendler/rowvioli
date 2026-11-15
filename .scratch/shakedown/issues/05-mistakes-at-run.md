# 05: Mistakes named at run: key columns, types, pause, reason line, pooler, schema

**Blocked by:** 01

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/shakedown/spec.md`. Findings and repros: `.scratch/shakedown/*.md`. Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes against PostgreSQL in Docker, no import of the program. Spec "Testing Decisions" apply; each finding's repro is the first red test. Unconfirmed findings (no ✓) are reproduced first and dropped if they do not go red.

## What to build

Spec stories 27–32, 35–38 and the decisions under "Mistakes named" that concern a run.

- Key checked against the first chunk's columns before staging: "table X has no column idd; it has: id, v".
- Unknown connector type lists installed types; an installed connector that fails to import reports its import error.
- `run` without names, nothing loaded, tables pausing: one stderr line (how many, earliest due, `rowvioli run <source>`); stdout JSON and exit code unchanged.
- `run <source> <name>` suggests the one enabled table ending in `.<name>`.
- Environment checks name every missing variable at once.
- A reason is the first line of the driver message, ADBC/nanoarrow wrapper prefixes removed, no traceback or absolute path; empty message → "the driver gave no message" with the step. Cut once where the reason is stored.
- Control connection: `pg_backend_pid()` in two transactions; differ → fail "a connection pooler in transaction mode is in front of the target; use session mode". Suite tests only the direct-connection pass; measure pgbouncer once by hand and record in `docs/measurements.md`.
- A run creates its schema only if it does not exist (worker without database `CREATE` loads into a pre-created schema).

## Acceptance criteria

- [ ] Each bullet has a test asserting what a person sees (exit code, stderr line, status reason).

## Comments

Resolved on branch `shakedown-fixes`, from sd-05 (cb66297). Review fixes: e97674d.
