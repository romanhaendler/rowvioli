# 01: The start: defaults, the key file, the type, small messages

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/out-of-the-box/spec.md` (read it first, also "Testing Decisions"). Behaviour reference: `README.md`, `docs/decisions.md`. Tests: `tests/conftest.py`, `rv` fixture. Documents are ticket 04: change no `.md` outside your ticket file, but list under `## Comments` every sentence the documents need.

## What to build

- `ROWVIOLI_KEY_FILE` unset means `worker.key` in the current directory, for `run` and `work`.
- `apply` and `apply --check` without a directory take `sources`.
- `run` and `work` whose key file does not exist stop at the start, exit non-zero, name the path and
  `rowvioli key new`. No run row is written.
- A `type` that is a near miss of `postgres`, `file`, `odbc`, `rest` fails `apply` and `apply --check`
  with "did you mean"; `sqlite` or `weather` pass.
- `rowvioli key new --help` prints help that names `new` and what it writes.
- The `odbc` connector without the system library (`libodbc`) fails with a reason that names the library to
  install, not an import traceback. (Simulate the failed import if no slim image is at hand; say how.)
- Lead: `run` prints `{"tables": {}}` after a changed `target_table` until the table is due. Reproduce; fix only if red.

## Acceptance criteria

- [ ] In a fresh directory with only `ROWVIOLI_TARGET_URL` set: `key new`, `apply --init`, `run`, `status` give a mirror.
- [ ] `run` without a key file: one line with the path and `rowvioli key new`, exit non-zero, `_rowvioli.runs` empty.
- [ ] `type = "postgress"` fails `apply --check`; a custom type passes.
- [ ] The whole suite is green.

## Comments
