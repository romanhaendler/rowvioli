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

## Comments

Deviations from README "Target schema" made by the implementation (impl-01):

- `sources` has three columns the README does not list: `target_schema`, `max_delete_share`, `max_seconds`. The README's list has only `options` for them, but `options` is what goes to the connector unchanged, so rowvioli's own settings needed columns.
- `tables.source` holds the source's name, not its id, because the README's request example filters `WHERE source = 'erp'`. The table lock uses `sources.id`, so the claim and the view join on the name.
- `meta` is one row with the columns `schema_version` and `max_running`, not key/value pairs.
- The view `status` has more columns than the README names (age, due_at, status): also `id`, `source_id` (the two lock numbers), `source`, `source_table`, `target_table` qualified with the schema, `max_age`, `loaded_at`, `attempted_at`, `requested_at`, `attempts`, `reason`. It shows only enabled tables of enabled sources.
- The exponent of the pause is capped at 30 doublings, so a table with very many attempts cannot overflow the interval. The cap at `max_age` applies long before.
- `init` drops and recreates the view each time. The tables are created only if missing and are never migrated.
- `key new` writes `worker.key` and `worker.pub` into the current directory, both base64, and refuses to overwrite an existing file. The README does not name the private key file or say what happens to an existing one.
- `key_id` exists in `sources`, but nothing fills it yet.
