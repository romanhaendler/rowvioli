# 04: Checks and schema changes

**Blocked by:** 03

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** Before publishing, a run checks zero rows, columns, key against the mirror's primary key, key unique and not null, and after the diff the share of deletions against `max_delete_share` (a table without a key counts its shrinkage); any failure fails the run and leaves the mirror unchanged. Schema changes (decision 17): a new source column is added to the mirror and its change log inside the publishing transaction under a `lock_timeout`; a missing column or a changed type (as the driver shows it) fails the run. `max_delete_share` set on a table overrides the source's.

- [x] The prototype's check tests pass (adapted: a new column is now added instead of failing)
- [x] A new source column appears in the mirror and the change log with values; a dropped column and a changed type each fail the run and leave the mirror unchanged (spec test 12)
- [x] Table-level `max_delete_share` overrides the source's (spec test 13)

## Comments

- Checks live in `check()` and `limit()` in `src/rowvioli/load.py`. New columns are added by `widen()` inside the publishing transaction, to the mirror and to an existing change log (which also catches columns added while `log = false`).
- The `lock_timeout` for adding a column is 10 s. Neither spec nor README names a value.
- A row whose new column is null in the source is not an update: after `ADD COLUMN` its mirror row already equals it. So the change log of the run that adds a column holds only the rows with a value in it, not every row.
- Reasons: `column X is missing in the source`, `column X has changed its type from A to B`, `the key [...] differs from the mirror's primary key [...]`, `a key column of (...) is null`, `a key combination of (...) occurs twice`, `the source delivered zero rows`, `N % of the rows would be deleted`.
