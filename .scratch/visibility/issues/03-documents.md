# 03: The documents: the lines, `status`, one new decision

**Blocked by:** 01, 02

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/visibility/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program.

## What to build

Spec stories 35 to 37 and the implementation decisions "A new decision" and "Documents". Documents only, no code.

- `docs/decisions.md`: one new decision under the next number, with Decision, Why, Price, Rejected as the earlier ones have them; the rejected alternatives are listed in the spec.
- `README.md`: the usage block ends with `rowvioli status`; "Commands" gets `status`; "Workers" or "Operation" lists the lines of a worker with one example each; the web UI row "Show complete log lines" names what the worker's log system now receives.
- `GLOSSARY.md`: no new term. Check that "log" still means the change log and `runs`.
- Every example is copied from what the commands on this branch really print (run them), not from the spec.

## Acceptance criteria

- [ ] The measure of the spec ("Further Notes"): one paragraph for the lines, one for `status`, no setting introduced.
- [ ] The examples in the README match the real output of `work` and `status` in wording and columns.
- [ ] No sentence in README, GLOSSARY or `docs/` still says that a worker prints nothing or that the status needs `psql`.

## Comments

Resolved on branch `visibility`, from vis-03 (30d314d). Review fixes: 2373115.
