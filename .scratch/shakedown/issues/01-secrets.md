# 01: Secrets: REST path, file confinement, scrubbing, the target's password

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/shakedown/spec.md`. Findings and repros: `.scratch/shakedown/*.md`. Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes against PostgreSQL in Docker, no import of the program. Spec "Testing Decisions" apply; each finding's repro is the first red test. Unconfirmed findings (no ✓) are reproduced first and dropped if they do not go red.

## What to build

Spec stories 1–9 and the implementation decisions under "Secrets" (TLS in the README, story 10, belongs to 06).

- REST `path` must start with `/`; the joined URL keeps scheme, host and port of the connection URL, else the run fails naming the option. `apply` repeats the `/` rule for type `rest`. Test with a second listening server that must receive nothing.
- `file` table resolved inside the connection's resolved `path`; absolute names and `..` fail naming the table.
- Scrub every secret as written, stripped, and in repr-escaped form; existing URL/ODBC forms stay.
- For the target, scrub only the password of `ROWVIOLI_TARGET_URL`, in every command.
- REST type mismatch names table, column, expected type, not the value.

## Acceptance criteria

- [ ] A token ending in `\n` never shows in status, runs, log or `run` JSON.
- [ ] `path = ".evil.com/x"` fails the run naming `path`; the second server sees no request.
- [ ] `../outside.csv` and an absolute table name fail naming the table.
- [ ] A target error shows user and host, not the password.

## Comments
