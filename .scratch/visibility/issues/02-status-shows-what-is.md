# 02: `rowvioli status` shows what is

**Blocked by:** None (can start immediately)

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/visibility/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program.

## What to build

Spec stories 22 to 34 and the implementation decisions about `status`. A new command in `src/rowvioli/cli.py` next to the others: optional source and table like `run`, one query on `_rowvioli.status`, an aligned text table on stdout with the columns `source table max_age age due status reason`, ordered by source and source table.

- It formats and computes nothing: status, `due_at` and progress come from the view (enabled tables only, as the view has them). The wording of `due` (`now`, `in 20m`) is derived from `due_at` and the target's clock, in the query.
- Durations in the definition's notation, largest two units (`5m`, `1h 3m`): one small function next to `definition.interval`, the direction that parses.
- A loading table shows its progress in place of a reason; an empty progress is no error. Never loaded: `new` and an empty age.
- Needs `ROWVIOLI_TARGET_URL` only, no key, no connector. Exit 0 whenever the state could be printed. A target without `_rowvioli` gives the same "run `rowvioli init` first" as `apply` (see `target.connect`).

## Acceptance criteria

- [ ] Spec "What is tested" 9 to 12, in `tests/test_status.py` or a file next to it, with facts written by SQL and fixed dates, no simulated clock.
- [ ] The existing tests pass unchanged.
- [ ] No documents in this ticket (ticket 03).

## Comments

Resolved on branch `visibility`, from vis-02 (5a0df3d). Review fixes: 2373115.
