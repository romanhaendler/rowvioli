# 02: `at` and `timezone` in the definition, `apply`, one run through the loop

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/load-times/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program.

## What to build

Spec sections "The definition" and "Checking". Touches `src/rowvioli/definition.py`, `src/rowvioli/sql/apply.sql`, tests.

- `at` and `timezone` are table settings: settable for a source, overridable for a table, the table's `at` replaces the source's, `at = []` switches it off. `apply` stores them on the table's row.
- `apply --check` (no target) refuses: `at` as a plain string, an entry that is not `HH:MM` from `00:00` to `23:59`, a non-empty `at` without `timezone`, an unknown `timezone` (stdlib `zoneinfo`, no new dependency). Messages name file, source, table and the setting, like the existing ones.
- `apply` fails and changes nothing when the target's Postgres does not know a time zone.

Found while checking the spec against the code, part of this ticket:

- Unknown keys of a source or table are passed to the connector as options today. `at` and `timezone` must not reach the connector.

## Acceptance criteria

- [ ] Spec "What is tested" 12, 13, 14 in `tests/test_apply.py` (prior art: the parametrised invalid definitions).
- [ ] Spec test 15 in `tests/test_run.py`: fresh by maximum age, load time after the last run, loaded by `run`, not loaded again by the next `run`.
- [ ] A definition with `at` and `timezone` loads through the `file` or `postgres` connector without the connector seeing them.

## Comments
