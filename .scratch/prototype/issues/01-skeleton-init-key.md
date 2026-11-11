# Skeleton, test harness, `init`, `key new`

Status: ready-for-agent
Blocked by: none

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

- uv project (Python >= 3.11; deps `pyarrow`, `adbc-driver-postgresql`, `pynacl`), console script `rowvioli` with the command dispatch for `init`, `key new`, `apply`, `run`, `work` (the last three may be stubs that exit non-zero).
- The control connection module (ADBC only, decision 28; keepalive settings from "Failures" in the README).
- `init`: schema `_rowvioli` with `sources`, `tables`, `runs`, `meta` and the view `status` exactly as the spec's "Bookkeeping in the target" and the README's "Target schema" describe. Idempotent.
- `key new`: private key file (mode 600) and public key file.
- Test harness (pytest, spec "Testing Decisions"): a session fixture starts two throwaway Postgres containers (source, target) on **random free host ports** with unique container names, so several worktrees can run the suite at the same time, and removes them afterwards. Helpers to run `rowvioli` as a real process with an environment, to write a definition directory, and to query both databases. Tests never import the program.

## Acceptance criteria

- [ ] `uv run pytest` passes from a clean checkout with only Docker running.
- [ ] `init` twice leaves the same schema, `meta` holds a schema version and `max_running` = 20.
- [ ] The view `status` returns `new` / `ok` / `failed` (`worker lost` without a reason) and the `due_at` and pause rules of the spec for rows inserted by the test with SQL (spec tests 11 pause arithmetic, 20, 22 as far as possible without a run).
- [ ] `key new` writes both files, private one with mode 600.
