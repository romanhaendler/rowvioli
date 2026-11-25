# Shakedown 2026-11-25, third wave: the personas that had not run, before 0.5.0

Status: resolved (every finding is in `.scratch/schema-changes/issues/17-third-round.md`)

Five Sonnet agents on a wheel built from `sc-15` at 2583551 (tickets 15 and 16 built, the review of 15 not yet
in; version set to `0.5.0.dev2` for the run): P1 beginner (also the upgrade without reading), P3 staff engineer
(every sentence of the documents about changes of shape against the wheel, the upgrade with 500,000 rows), P4
vibe coder (eight requests from the documents alone, a SQLite connector of his own through every change), P16
migrating team (onto existing tables, and the habit of changing the target by hand), P22 ELT specialist (65 cases
of schema drift). Not run: the reviewers P23, P24, P27.

## What they found

| From | Finding | Where it went |
|---|---|---|
| P16 | A consumer's foreign key onto a mirror fails every run that updates or deletes a referenced row, no way out (older than the branch) | ticket 17, M1 |
| P16 | A table or view of the team's named `<t>__log` or `<t>__history` is taken for the program's: a stop that tells to drop a source column, SQL that does not run, withheld SQLSTATEs | ticket 17, M2 |
| P16 | The source drops a column and a person drops it from the mirror by hand before the run: the history shows its last values as current for good | ticket 17, M3 |
| P16 | A type changed by hand to another family while the source changed too: 42804 withheld, no way out | ticket 17, M4 |
| P16 | Wording of two stops (a team's own column on a table whose change log is about to begin; a key changed by hand before the run); adopting a table deletes the rows the source lacks without a word | ticket 17, M5 to M7 |
| P1, P22 | A source table that does not exist (misspelt, renamed, moved) says only `SQLSTATE 42P01 … may hold a row's values` | ticket 17, L2 |
| P1 | A password with `@` or `/` written into the URL: the wrong cause and a fragment of the password in the reason | ticket 17, L3 |
| P1 | After a variable is corrected the old connection is still used, and nothing says `apply` | ticket 17, L1 |
| P3 | "Replaying it … gives the mirror, always" needs an order within a run after a change of key (`D` before `I`) that no document names | ticket 17, E1 |
| P3 | The stop for a definition without a key tells to drop the mirror too, where the change log alone is enough | ticket 17, E2 |
| P4 | `catalog` is explained only in the guide for licensed software; `driver_version` is stored unchecked; a connector that delivers what the contract does not allow gives raw library text | ticket 17, J1 to J3 |
| P22 | An array whose element type widens is another family; no document says how arrays are classed | ticket 17, G1 |
| P3, P22 | The recipe "the table at a moment is one condition" lacks the sentence on retired columns; the README's header says 0.4.1 | ticket 17, G3; with the version |

## What held up

- P22: 62 of 65 cases of drift exact in mirror, replay and history at every earlier moment; every stop met had a
  way out that worked literally; a stopped run published nothing.
- P3: every claim checked about a dropped, returning, widened, renamed column and a changed key; the upgrade from
  0.4.1 with 500,000 rows (`init` 0.27 s, the first run 2.5 s without rewriting), the three stuck tables resolved;
  going back refused in both directions; costs as the documents say (a dropped column on 500,000 rows 3.4 s).
- P4: all eight requests from the documents alone; the SQLite connector through an added, renamed, dropped column,
  a type of another family and a changed key with mirror, replay and history equal after each step.
- P1: the upgrade by `pip install -U` and `run` leads to `init` in one line; every beginner's mistake of the entry
  got a message that says what to do.
- P16: tables that match the source are taken over cleanly; the team's own columns stop with a way out that
  works; indexes, views and grants stay.

## Cost

Five Sonnet agents, 3 to 8 minutes each. No image pulled.
