# Shakedown 2026-11-24: schema changes, before the release after 0.4.1

Status: needs-triage (what is fixed before the merge is in `.scratch/schema-changes/issues/11-after-the-shakedown.md`; what stays is marked "left")

One wave of six Sonnet agents on a wheel built from the branch `schema-changes` (its version set to
`0.5.0.dev0` for the run), narrowed to what the branch changes: a mirror follows its source's columns, types
and key where a change log keeps what was (decision 54). U1 upgrade from the released 0.4.1 (a new entry,
with the wheel of the tag beside it), H1 install and target (Postgres 14 and 17, pgbouncer, least rights),
H2 hostile source data narrowed to changes of shape (Postgres, file, REST), H4 operation, P18 security,
P20 consumer and auditor. Not run: P1, P3, P4, P16, P22 and the reviewers. Not covered by any: ODBC, Excel
and JSON files, a real `pg_dump`, a superuser `init`, two `work` processes on one table, `renamed` applied
during a load, a real 0.4.1 fleet over days.
✓ = confirmed in the source by the coordinating session, or reported red by two or three agents on their own;
the rest are leads from one agent, and a ticket that starts from one reproduces it first.

## The five that matter most

1. ✓ **After the upgrade, a primary key that a person changed by hand on 0.4.1 is taken for the change log's
   former key** (U1; `load.py:210`: without a record the difference counts as a change of key). The run
   writes a `D` and an `I` per row, records `by = definition`, and the history view at a moment before the
   upgrade gives 13 rows where the table had 10. Ticket 05 knew the departure and judged "no data is lost";
   the history is wrong.
2. ✓ **A grant given on a history view by name is gone after any run that changes columns or key** (H1, P18,
   P20, on Postgres 14, 16 and 17). The branch drops and creates the view (`load.py:563`) where 0.4.1 only
   replaced it. Grants from default privileges come back; the mirror and the change log keep theirs.
3. ✓ **A way out that damages: `renamed` onto `_op`, `_run` or `_loaded_at`** (P18; `load.py:123`, `:133`).
   The reason tells the person to rename the change log's own column `_op`; following it fails every later
   run. `apply` took the definition.
4. **A way out that is not needed and leads into a second stop: "a name that is taken"** (H2). The retired
   name `amt__2` meets a real column; a second run without doing anything passes, because the name is then
   `amt__3`. Who follows the reason ends with the old values under a name cut off from the history.
5. **A consumer's own trigger or constraint message with the row in it reaches the status, `_rowvioli.runs`
   and stderr** (P18: `raise exception 'bad row %', NEW`). Postgres's own messages showed no value. For the
   owner: whether the rule "a reason never shows a value" covers a message a consumer wrote.

## What they found

| From | Finding | Where it went |
|---|---|---|
| U1 | 1 above ✓ | ticket 11 |
| H1, P18, P20 | 2 above ✓ | ticket 11 |
| P18 | 3 above ✓ | ticket 11 |
| H2 | 4 above | ticket 11 |
| P18 | 5 above | left: for the owner |
| P20 | The query "what changed, and why" in `docs/target.md` and the listener's recipe read `columns__log`, which the documented auditor's role may not read | ticket 11 (documents) |
| P20, H4 | "A prepared `SELECT *` fails once" holds only for a statement prepared anew: one that stays prepared fails on every call until it is prepared again; a widened type does it too | ticket 11 (documents) |
| P20 | A reader that lists the columns from `information_schema` and then selects them gets `column does not exist` across a change of shape (11 of 11) | ticket 11 (documents) |
| U1 | A 0.4.1 worker left running through `init` writes about 12 lines a second, with no cause and no pause, until it is stopped; nothing is damaged | ticket 11 (documents: stop the old workers first, and what a forgotten one does) |
| U1, H1 | Without the two grants every table fails with `permission denied for table columns__log`, which names neither the right nor that `init` printed the grants; `the target has schema version 3, this program works with version 4` does not say `rowvioli init` | ticket 11 |
| P18, H2 | A `numeric` of more than 38 digits is refused as "such as NaN or Infinity" | ticket 11 |
| H2 | A REST column whose type does not match the JSON stops with `column amt is not text`, no way out; `_op cannot be freed` says no way out | ticket 11 |
| P18 | A newline in a column's name cuts the reason at it, and the way out is lost | ticket 11 |
| P18 | A comment on `_op` edited by hand gives Postgres's own message (`column "i" does not exist`), which does not name the comment. It never reached SQL as code | ticket 11 |
| P18 | The way out of "the retired name is longer than 63 bytes" leads into a second and third stop, one column each | left |
| P18 | Who may read `columns__history` reads every schema's column names, and the indexes and grants in the notes; `docs/operation.md` offers the view to consumers | ticket 11 (documents say so) |
| P20 | A stop names the dependent objects of one layer; three nested views cost three runs | left |
| P20 | The columns table says `city` for a past moment where the history view already says `town`: a rename is applied to old rows too, and `was` is the only bridge | left: by design, documents |
| P20, H4 | A dropped column or a changed key costs a log row or two per row; "what changed yesterday" on the log then lists every row. 40 changes of a 100,000-row table: 4.2 million log rows, 383 MB | left: the price the spec accepted |
| H1 | The count `~N` of a run that drops a column counts change-log rows (`~60` for 3 changed rows) | left |
| H1 | The worker needs no `SELECT` on `columns__log`, the documents grant it | left |
| H2 | A `numeric(10,2)` widened to plain `numeric` loses its trailing zeros (`3.00` reads `3`); the values are equal | left: documents |
| H2 | A CSV header that loses a column leaves it empty in the mirror for good, and no page says how to be rid of it on purpose | left: documents |
| H1 | pgbouncer in transaction mode: no clear message, and tables stay `loading` until the pooler restarts. Not compared with 0.4.1 | left |
| H2 | A source table dropped and created anew with other columns stops with "76 % of the rows would be deleted" only; `max_delete_share = 1.0` loads it right | left |
| H4 | A table that never loaded starves while older ones stay overdue (`claimable.sql`, unchanged since 0.4.1 ✓): 34 of 50 tables still `new` after four minutes with `max_age = "1s"` | left: not of this branch |
| H4 | The target restarted during a run: the last line is Postgres's bare `FATAL: terminating connection` | left |

## What held up

- The history at every earlier moment against a snapshot, the change log replayed to the mirror, and mirror
  against source by an exact comparison, after every run of H2 (26 tables, every family of types, renames
  proven and stated, keys changed and changed back, hostile names) and of P20 (ten moments, three changes of
  key). Every stopped run changed nothing.
- H4: 36 kills (SIGKILL, SIGTERM, SIGINT) at random moments of runs that add, drop and widen, a kill during
  a change of key on 500,000 rows, the target restarted, the source cut: never a half state, the next run
  repaired everything, a notification for every commit and none for a rollback. A reader's long transaction
  makes the run give up after 10 s with the documented reason; it never waited while holding a lock.
- No injection through any name in the new statements, the comment on `_op` or `renamed`; the statements a
  reason prints are safe to paste for hostile names. No secret in any output.
- U1: every table stuck on 0.4.1 but the one of finding 1 resolved after `init`, by itself or by the way out
  its reason gave; `init` as the wrong role changes nothing; old and new program refuse each other's target
  version; the grants `init` prints are the right ones.
- H1: the same on Postgres 14 and 17 and through pgbouncer in session mode, with a worker of exactly the
  documented rights; the quickstart in `python:3.11-slim`.
- Measured on 500,000 rows (H4): a dropped column 3.2 s with readers locked out 1.4 s; a widened `numeric`
  4.7 s and 2.4 s; both together 6.8 s and 3.4 s.

## Lessons for the procedure

- Two agents ended processes by name (`pkill -f listen.py`, `pkill -f "http.server 8765"`) and may have hit
  another agent's. The brief should say: end only processes you started, by their PID.
- An upgrade host found the finding that matters most. It belongs in `personas.md` as an entry of its own.

## Cost

Six Sonnet agents, 7 to 29 minutes each. Images pulled: `python:3.11-slim`, `edoburu/pgbouncer`.
