# 01: The start: defaults, the key file, the type, small messages

**Blocked by:** none

**Status:** resolved

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

Built (branch `ootb-01`):
- `cli.py`: `run` and `work` resolve `ROWVIOLI_KEY_FILE` (empty counts as unset) to an absolute path, default `worker.key` in the
  current directory, and stop at the start if it does not exist (path and `rowvioli key new`, no run row). They set the variable to
  the absolute path, so the run processes use the same file. `apply` takes `sources` without a directory. `key new --help` says
  what it writes.
- `definition.py`: a source `type` that is a near miss of `postgres`, `file`, `odbc`, `rest` (rule of `typos`) fails `apply` and
  `apply --check` with "did you mean". Note: `rest` and `file` are four letters, so a custom type one letter from them (`test`,
  `fine`) fails too; the spec accepts this.
- `connectors/odbc.py`: an `OSError` on `import arrow_odbc` becomes `ImportError("the ODBC driver manager is missing; install
  unixodbc (libodbc)")`, which `contract.connector` already shows as `cannot be loaded`. Verified here for real: this Mac has no
  unixodbc, so the existing no-driver test ran and went red on the new sentence (the old text only held a dlopen path).
- Lead (target_table changed, `run` prints `{"tables": {}}` until due): went red, so fixed. `apply.sql` resets `attempted_at` to NULL
  when the target schema or table of a table changes, so the table is `new` and due at once. No schema change.
- Tests changed: `test_run_and_work_name_a_missing_variable_at_start` and `test_every_missing_variable_is_named_at_once` no longer
  take `ROWVIOLI_KEY_FILE` as a required variable; `test_an_unknown_connector_type_lists_the_installed_ones` uses `weather`, since
  `postgress` now fails at `apply`.

Documents need:
- README: the start is `key new`, `apply --init`, `work`, `status` with `ROWVIOLI_TARGET_URL` alone; `ROWVIOLI_KEY_FILE` defaults to
  `worker.key` in the current directory; `apply` without a directory takes `sources`. A missing key file stops `run` and `work` at
  the start. The existing sentence on typos of settings gets: "So does a `type` one or two letters from `postgres`, `file`, `odbc`
  or `rest`; any other type passes, since `apply` does not know the connectors."
- README (odbc): without the driver manager the connector fails with "install unixodbc (libodbc)".
- README or decisions: a changed `target_table` or `target_schema` makes the table new again, due at the next run (it moves nothing,
  the old tables stay); this is the one worker-written column `apply` resets (`attempted_at`).
- decisions: 14 (apply does not know the connectors) gets the exception of near misses of the four built-in names.
- open-points: strike "no key file / mistyped type shown only at the run", the `{"tables": {}}` lead and the libodbc message.
