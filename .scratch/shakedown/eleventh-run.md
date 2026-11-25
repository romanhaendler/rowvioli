# Shakedown 2026-11-25, fourth wave: the reviewers and the final check, before 0.5.0

Status: resolved (every finding is in `.scratch/schema-changes/issues/18-fourth-round.md` or `19-fifth-round.md`, in the tests merged from
`sc-18`, or declined below with its reason)

The three reviewers that had not run, on Sonnet, against the branch `sc-17` at 09eb9f7: P23 the maintainer's
successor, P24 the test-quality auditor, P27 the deleter. Then, on `schema-changes` at 1fdb4b3 (after ticket 17): F1,
a Sonnet host on the wheel `0.5.0.dev3` that tried the fixed faults of the second and third wave again from the
outside, and a fresh Opus review of the code as it is. Not run again: ODBC, REST and Excel at runtime, Postgres 14
and 17 (second wave).
✓ = shown red by a script of the finder's.

## What they found

| From | Finding | Where it went |
|---|---|---|
| Review ✓ | A column a person drops from the mirror while the source keeps it (the way out the stop for a type changed by hand prints) is not closed in the change log: its replay is not the mirror, with the run `ok` | ticket 18, item 1 |
| Review ✓ | The stop for a comment on `_op` that names another key last gives a text that changes nothing when a person changed the primary key to the definition's new key | ticket 18, item 2 |
| Review ✓ | A key column dropped from the mirror by hand stops with a withheld SQLSTATE 42703 and no way out | ticket 18, item 3 |
| Review | Leads: the note of the keys across target names A, B, A; a retired column's note of an old target name; a row deleted from the mirror between diff and publish | ticket 18, item 4 |
| Review | README: "a worker takes the most overdue table" leaves out the tables never tried | ticket 18, item 5 |
| Last check ✓ | After ticket 18, an Opus check of its code: a primary key changed by hand on a table of 0.4.1 with no record (to the definition's new key, to a third, with the mirror renamed) ends `ok` with a wrong history, or with a way out that gives one | ticket 19 |
| CI | With `duckdb` 1.5, the floor, a Parquet `timestamptz` and `time` of nanoseconds are cut before the connector sees them | the floor is `duckdb>=2` (7ac0050) |
| P24 | 11 of 38 mutations of `load.py` and `claimable.sql` survived the tests (`ONLY` of the publish's update and delete, the closing rows' tiebreak and `OR`, `noted()`'s `<=`, the lock's SQLSTATE, the retry's condition, 63 bytes, a `retired` that is no text, the order of the claim) | a test each, red under its mutation: merged from `sc-18`; one is an equivalent mutant |
| P27 | A clause that cannot hold in the key's change (`not was or dropped`) | removed (1fdb4b3) |
| Ticket 17's review | A consumer's exclusion constraint under a swap of values stops with no way out | merged from `sc-18` |
| P23 | The reserved names are written out in the tests, not read from the program | declined: the tests never import the program (`tests/conftest.py`) |
| P27 | The condition `key and log and log_columns` repeated, a slice of no effect, sentences repeated across documents | declined: taste, and the repeated condition guards if the first check is ever loosened |
| F1 | `apply` takes a URL with an invalid `%zz`; the run then fails with libpq's words and no password | declined: the cause is said and nothing leaks |

## What held up

- F1: no value of a row in any output over about 25 cases (every SQLSTATE of the second wave's list, a consumer's
  `RAISE` in a constraint's wording, a missing source table, the new stops for a consumer's unique index and foreign
  key, whose ways out it followed to `ok`). The hunt's four faults green. A consumer's foreign key onto the mirror,
  plain, `ON DELETE CASCADE` and `SET NULL`, across updates, inserts and deletes: the consumer's rows follow what
  the source justifies. A team's own `<t>__log` and `<t>__history` refused. After every scenario mirror = source,
  replay = mirror, history at each earlier moment = its snapshot.
- Review: about 20 combinations of rename, widening, key change, retired and closed columns in one run, each
  checked the same three ways; the publish retry and the counts by reading; no path of a value into a reason;
  18 sentences of the documents against the code.
- P24: 27 mutations killed; hypothesis found no counter-example for `quote` and `literal` against Postgres 16
  (400 examples each) nor for `scrub` (2000).
- P23: four everyday changes; none broke a test for a reason she could not see. The dearest is a new column in the
  status view, which needs a schema version.
- P27: no unused name (ruff F and ARG), no contradiction between the documents and the code.

## Cost

Four Sonnet agents, 6 to 60 minutes each; one Opus review, 11 minutes. No image pulled.
