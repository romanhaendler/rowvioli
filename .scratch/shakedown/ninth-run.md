# Shakedown 2026-11-24, second wave: schema changes, before 0.5.0

Status: resolved (every finding is in `.scratch/schema-changes/issues/15-second-round.md` or
`16-second-round-connectors.md`, as each line says)

Six Sonnet agents on a wheel built from `schema-changes` at c917551 (version set to `0.5.0.dev1` for the run),
after tickets 11 to 14: each tried the first wave's findings again (`eighth-run.md`) and went where that wave had
not been. U1 upgrade (a fleet of 13 tables in every state, `init` twice, at once, killed), H1 install (Python 3.11
to 3.13, Postgres 14, 16, 17, pgbouncer, roles and databases with unusual settings), H2 hostile data through
Excel, JSON, Parquet, ODBC and REST, H4 operation (two workers, `apply` beside them, kills, a real `pg_dump`,
readers with locks), P18 security (a value in a reason, by every error that could be provoked), P20 consumer and
auditor. Beside them three Opus reviews of the branch (spec, standards, a hunt for faults against a database),
whose findings are in ticket 15. Not run: P1, P3, P4, P16, P22 and the reviewers.
✓ = confirmed by the coordinating session or shown red by two on their own.

## The first wave again

Every finding of `eighth-run.md` holds, but two: a newline in a column's name no longer cuts the reason, yet the
statement the reason prints does not work when pasted (P18); the target restarted before a run has claimed still
ends in Postgres's bare `FATAL` (H4).

## What they found

| From | Finding | Where it went |
|---|---|---|
| P18 ✓ | A row's value reaches a reason through a SQLSTATE of a class taken for names: 42601 (`to_tsquery`, `::regtype`, `::regclass` with too many dots, also with a line break in the value), 42602, 58P01 | ticket 15 |
| P18 | A consumer's `RAISE` in the wording of a constraint message is shown, value and all | ticket 15 |
| P18 | The statement a reason prints for a column whose name holds a control character fails when pasted | ticket 15 |
| P18 | A comment on `_op` of the right shape that names a wrong key is believed | ticket 15 |
| P18, hunt | A history view whose owner a person changed fails every changing run with `permission denied for table …__log` | ticket 15 |
| P20 | A consumer's trigger that rewrites the mirror's values: a `D` and `I` per run for the row, and after a change of key two open versions in the history | ticket 15 |
| P20 | A publication on the mirror stops a change of key with Postgres's bare message | ticket 15 |
| P20 | A child table the worker does not own stops every change with `must be owner of table child`, no way out | ticket 15 |
| P20 | `was` of a column that went and came in another family still names an earlier rename | ticket 15 |
| H2 | A key column of an unpinned Parquet file that changes family gets the way out `DROP COLUMN "id"`, which destroys the mirror | ticket 15 |
| H2 | A missing ODBC driver library is withheld as "may hold a row's values" | ticket 15 |
| H2 | REST: a key field named in another case gives only `a key column of ("id") is null` | ticket 15 |
| H2 | ODBC through psqlODBC: `float8` arrives as `real`, a date `infinity` as today, `timestamptz` as `timestamp`, `bool` as text; a timestamp BC is blamed on the target (older than the branch) | ticket 16 |
| H2 | A Postgres source's timestamp `infinity` fails with `Error occurred writing COPY data:` alone (older) | ticket 16 |
| H2 | Excel: dates as serial numbers, a pin on them stops with a way out that does not work, 19-digit integers lose digits (older) | ticket 16 |
| H2 | A Parquet struct fails with the driver's C++ message (older) | ticket 16 |
| U1 | Two `init` at once: the loser ends with a bare Postgres message and exit 1 (the result right 5 of 5) | ticket 16 |
| U1 | A superuser `init` gives the new objects another owner; `init` as the wrong role says only `must be owner of table runs` | ticket 16 |
| H1 | A LATIN1 target stores `Müller` as `MÃ¼ller` with the run `ok`; with a non-ASCII name `status` ends in a traceback (older) | ticket 16 |
| H1, H4 | A failure before the claim never says its cause (a read-only role, a target restarted at the start) | ticket 15 |
| H1 | A role's `statement_timeout` ends a run with the driver's wrapper and no way out; `permission denied for schema` does not say CREATE | ticket 15 |
| H1 | A missing extra is not named (`No module named 'duckdb'`) | ticket 16 |
| H1 | The README's header says 0.4.1 | with the version |

## What held up

- U1: the fleet through the upgrade as superuser, as a worker of least rights and through pgbouncer in session
  mode: every table loaded or gave a way out that worked; history at six earlier moments against snapshots, replay
  and mirror against source. Finding 1 of the first wave in five variants. `init` killed with KILL, INT and TERM
  changes nothing.
- H4: six chaos runs of up to 300 s (two `work`, a looping `run`, `apply` from two places, a change of shape every
  second, more than 80 kills): no half state, 0 differences of mirror, replay and history at up to 236 moments, a
  notification for every committed change and none else. A `pg_dump` taken in the middle, restored, and the
  program going on. Readers were never blocked by a waiting run.
- H2: every change of shape through CSV, Excel, JSON, NDJSON, Parquet, ODBC and REST exact in mirror, history and
  replay; no recognisable value in any output over 36 file cases, REST and ODBC failures.
- P18: no injection through any name; grants on a history view of every kind survive; class 22, P0 and the four
  undefined-object codes withheld.
- P20: every documented auditor's and listener's query with exactly the documented rights; a stop names all
  dependent objects through four layers; the story of a table through twelve changes read from
  `columns__history` alone.
- H1: ten installs (no extra, each, all) on 3.11 and 3.12; the quickstart literally; the matrix of changes on
  Postgres 14, 16 and 17 under a non-default `search_path`, `standard_conforming_strings = off`, role timeouts,
  quoted names, three collations.

## Cost

Six Sonnet agents, 10 to 41 minutes each; three Opus reviews, 4 to 14 minutes. Image pulled: `python:3.11-slim`.
