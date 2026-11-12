# 01: New skeleton, `init`, `key new`, CI

**Blocked by:** None (can start immediately)

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** The program written anew. The prototype's code under `src/` is removed; the new package has the module layout of `docs/package.md` (stubs where later tickets fill in), MIT `LICENSE`, version 0.1.0, core dependencies and the extra `file` (`duckdb`). `rowvioli init` creates `_rowvioli` with `sources`, `tables`, `runs`, `meta` and the view `status` (README "Target schema", spec "Bookkeeping in the target"), writes schema version 1 and `max_running` 20, and changes nothing when run again. Every command that uses the target refuses a target with another schema version and names both. `rowvioli key new` writes `worker.key` (mode 600) and `worker.pub`, never overwriting either. The control connection sets the keepalive parameters and `client_connection_check_interval` from README "Failures". The prototype's harness and its `init`, `key` and `status` tests carry over (adapted where 0.1 changes the view's columns). A GitHub Actions workflow runs the suite on Linux on every push. `docs/open-points.md` records B5 as decided.

- [x] `uv run pytest` passes from a clean checkout with only Docker running; containers and volumes are removed afterwards
- [x] `init` twice changes nothing; `meta` holds schema version 1 and `max_running` 20
- [x] A target with another schema version is refused by every target-using command, naming both versions (spec test 1)
- [x] The view `status` has the README's columns and computes `age`, `due_at`, `status` as the README's formula states (prototype status tests)
- [x] `key new` writes both files, private one mode 600, and refuses to overwrite either
- [x] CI workflow runs the suite on Linux on push

## Comments

- `meta` has a third column `definition` for the hash of the definition last applied (spec "Bookkeeping in the target"); the README's schema listing now names it.
- `init` runs the schema script only when `_rowvioli` is missing; on a target that has it, it only checks the version. A changed view therefore needs a new schema version, not a second `init`.
- The shared version check also refuses a target without `_rowvioli` with "run `rowvioli init` first", which ticket 02 asks of `apply`.
- `apply` (without `--check`), `run` and `work` are stubs: they open the target (so the version check applies), then exit 1 with "not built yet". `list` and `apply --check` exit 1 without touching the target.
- The status view keeps the prototype's columns; the progress columns come with ticket 06.
- CI (`.github/workflows/tests.yml`) was not run here; it needs a push to GitHub.
- `LICENSE` names "the rowvioli authors" as copyright holder; the owner may want his name there.
