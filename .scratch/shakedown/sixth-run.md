# Shakedown 2026-11-23: after 0.4.0, the entries that had not run

Status: needs-triage (the tickets are in `.scratch/after-0.4.0/issues/`; what has no ticket is listed below with what the owner has to decide)

One wave of five Sonnet agents on the released wheel 0.4.0 and, at the owner's wish, one bounded read of the
whole program on Fable. H4 operation in full, P1 Lena, P3 Dr. Brandt (first run), P20 consumer (first run), P24
test-quality auditor (partly: the mutation run on `definition.py` was refused by the session's permission check
and not worked around). Not run: H1, H2, P4, P16, P18, P22, P23, P27. Not covered by anyone: Windows, a real
systemd and cron, a clock change, a kill exactly inside the publish transaction, several workers against the
consumer's reader loop.
✓ = confirmed in the source by the coordinating session; the rest are leads from one agent, and a ticket that
starts from one reproduces it first.

## What they found

| From | Finding | Where it went |
|---|---|---|
| read | A run publishes into a target name that `apply` gave to another table meanwhile: the lock is on the table id, the name is read once ✓ (mechanism; outcome not reproduced) | ticket 07 |
| P1 | The README's "What you see" lacks the `▶ … started` line `run` prints, and nothing there says what `+3 ~0 -0` means ✓ | ticket 08 |
| P24 | `max_age = "1٣h"` passes the check (`\d`) and fails with the database's message ✓ | ticket 09 |
| P24 | Four mutants in the lines of 0.4.0 survive: the edges of `plain()`, the colour of `⚠`, the width 28, `flush()` in `out()` | ticket 10 |
| H4 | A worker started while the target is down exits at once; the documented unit has no `RestartSec`, so systemd gives up ✓ (source; not run under systemd). `ExecStart` is no absolute path | ticket 11 |
| P1 | `ROWVIOLI_TARGET_URL=localhost` names a connection option nobody typed; a key removed from the definition gets the reason for a changed key | ticket 12 |
| P3, P20 | No recipe for a column dropped in the source ✓; a consumer without `_rowvioli.status` cannot see that a mirror stopped; a `SELECT *` view does not gain a new column | ticket 13 |
| H4 | A run ended after `max_seconds`, or orphaned by a killed worker, leaves its query running in the source; every retry adds one | open: needs a decision (cancel before the kill, or a `statement_timeout` from `max_seconds` where the connector can) |
| P1, P3 | A password written plainly in a source file is accepted without a word; a short one mangles every message (`e***ist`) | open: `docs/open-points.md` knows the short secret; whether `apply` warns is the owner's call |
| P1 | The duplicate-key reason gives no example value | open: a value in a reason is source data in the target and in logs |
| P3 | A changed key passes `apply` and fails at the next run | open: `apply` does not look at mirrors today (decision 17) |
| P3 | Sections 9 and 15 of `docs/measurements.md` cannot be rerun from the repository | open: for the owner, the scripts are not in the repo |
| P20 | Wish: the time of the last successful load, readable without `_rowvioli` (dbt `source freshness`, Fivetran `_fivetran_synced`) | open: a design question |
| P3 | Wish: a `where` per table | no: README, a view in the source; a custom connector of 6 lines held |
| read | If the acknowledgement of the COMMIT is lost, or the `max_seconds` kill lands during it, `run` says `failed` although the data is published | open: small, Opus |
| read | More machinery than the job needs: `end_lost`/`LOST`/`record` beside the claim's `worker lost` and `max_seconds`; the zero-rows check beside the delete share; about 50 lines of did-you-mean | open: each would change a decision; the owner decides |

## What held up

- A reader never saw a half state: 638 comparisons of mirror, log replay and history during 50 runs, and 2000 reads of 100 000 rows during five full updates.
- A failed run left mirror and log byte for byte as they were; the log replayed to the mirror after every kind of change.
- `kill -9` of workers and of 25 run processes at random moments: every mirror converged, no row stuck as running.
- Four workers with three slots on twelve tables, three overlapping `run`, two `apply` at once: no table loaded twice, nothing broken.
- The target restarted, the source network cut, a full 70 MB volume: the real cause named, the mirrors kept, convergence afterwards.
- Upgrade both ways between 0.3.1 and 0.4.0 on one target.
- A beginner had her first mirrored table three minutes after the README block; the mistakes of the first run against 0.1 all get a message that says what to do.
- Every mutant in `colour()`, `say()` and `say_run()` died; seven property tests of 3000 examples each held.

## Cost

Five Sonnet agents and one Fable read (13 tool calls). Images pulled: none. Every container with the label
`rowvioli-shakedown` was removed by its agent.
