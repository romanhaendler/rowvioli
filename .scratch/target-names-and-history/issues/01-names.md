# 01: Names: a table says where it lives

**Blocked by:** none

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/target-names-and-history/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program. Disk: check `df -h .` and `docker system df` before and after; remove the containers and volumes your tests created.

## What to build

Spec stories 1 to 16 and the implementation decisions under "Names", plus "Schema version 3, no migration".

- `target_schema` at a table as well as at the source; `target_table` at a table only. `_rowvioli.tables` gets the column, `_rowvioli.sources` loses it; everything that prints or uses a target name reads the table's row.
- One check when the definition is read, across sources, without a target: no target name twice, counting `…__log` and `…__history`. It replaces the shared-schema rule and the check against disabled sources.
- Limits: schema 63 bytes, table 54 bytes, not empty, not `_rowvioli`.
- `apply` prints one line per table whose target name changes and moves nothing.

Not in this ticket: `_loaded_at`, the history view, the complete-log failures (02), README/GLOSSARY/decisions (04).

## Acceptance criteria

- [ ] Tests 1 to 9 of the spec's "What is tested" exist and pass (6 without its history-view half, which 02 adds); the existing tests for a shared `target_schema` are rewritten to the new rule.
- [ ] The whole suite passes.
- [ ] A definition that sets neither setting gives the same target names as before.

## Comments

Resolved on branch `target-names-and-history`, from tnh-01 (6cc2244). Review fixes: dc4cdb4.
