# 04: `status`, `list` and the error messages write no control characters to a terminal

**Status:** ready-for-agent

**Model:** Sonnet

From the review of 0.4.0 (`.scratch/shakedown/fifth-run.md`, row "review").

## What to build

A reason can quote source data (a failed cast echoes the value). 0.4.0 writes control characters as `?` in the worker lines (`plain()` in `src/rowvioli/work.py`), but:

- `rowvioli status` prints `reason` raw to stdout (`cli.py`, the status table);
- the message of a failed `list` (a connector exception text) and the target error reach stderr raw (`cli.py`).

Write them through the same filter. What is stored (`runs.reason`, the status view) and what is JSON (`run` on stdout, `list` output) stays as it is: JSON escapes already.

## Acceptance criteria

- [ ] A test puts a reason with ESC and `\r` into a table (a real failing load if cheap, else directly in `_rowvioli`) and `rowvioli status` prints it with `?`.
- [ ] A test for the `list` message.
