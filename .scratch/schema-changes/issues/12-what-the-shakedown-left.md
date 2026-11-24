# 12: What the shakedown and the reviews left, fixed at the owner's word

**Blocked by:** 11

**Status:** ready-for-agent

**Model:** Opus

The owner on 2026-11-24, after reading the shakedown: fix all of it. This ticket holds what ticket 11 does
not: the lines marked "left" in `.scratch/shakedown/eighth-run.md`, and the two faults older than this branch
that the reviews of tickets 10 found. Some are not of this branch (they are in 0.4.1 too); they are fixed here
all the same. Each starts from its red as a test at the existing seam.

## What to build

### Wrong values and lost rows (older than the branch)

1. **The postgres connector never stores a wrong `numeric`.** A value with more integer digits than a
   decimal holds can arrive as another value with the run `ok` (`1.5e400` arrived as `0`: Arrow's cast from
   text to `decimal256` wraps without an error). Such a value fails the run and names the column
   (`postgres._cast`), with the reason ticket 11 gives for more than 38 digits.
2. **A table that inherits from a mirror keeps its rows.** Diff and publish read and write the mirror with
   `ONLY`, so a consumer's child table (`INHERITS`) is neither read as part of the mirror, deleted from, nor
   counted towards `max_delete_share`. The entry in `docs/open-points.md` goes.

### A value in a reason

3. **A message that a consumer's trigger or constraint raises on the target never puts a row's value into a
   reason** (the owner: a reason never shows a value, always). For an error raised in the target that is not
   one of Postgres's own with a known shape, the reason is ours: what failed (the trigger, constraint or
   function Postgres names, its SQLSTATE), that its message is withheld because it may hold a row's values,
   and where a person reads it (the server's log). Names stay (decision 54; spec decision 15: a refusal that
   names a dependent object keeps its detail). Status, `_rowvioli.runs`, stdout and stderr.

### Ways out

4. **"The retired name is longer than 63 bytes"**: one reason names every column it holds for and a way out
   that leads out in one step, with no second stop behind it (P18 followed it into a second and a third).
5. **A stop for a dependent object names all of them**, through the layers (a view on a view on the history
   view; a materialized view), so one round of work clears the way. Where Postgres's detail lists them, show
   all of it; where it names one, read the rest from the catalogue.
6. **A source table created anew with other columns** stops with "N % of the rows would be deleted": the
   reason says what it may be (the source table was replaced, or emptied) and the setting that lets it
   through once (`max_delete_share`).
7. **A CSV or Excel column that is gone from the file for good**: find by test what removes it from a mirror
   with a change log without losing its history (it stays, empty, by ticket 08), and say it where a person
   meets it (`docs/loading.md`); if there is no clean way today, make one that fits the rule "where the
   definition names the columns, the definition is the catalog" and say which.

### Operation

8. **A table that never loaded does not wait behind tables that are overdue** (`src/rowvioli/sql/claimable.sql`:
   a new table counts as 0 against one overdue by many `max_age`): H4 saw 34 of 50 tables still `new` after
   four minutes with `max_age = "1s"` and `parallel = 8`. Never-loaded tables first, then as today. Read the
   decision that set the order (`docs/decisions.md`) and note the change there in the manner of "Changed by".
9. **pgbouncer in transaction mode says so.** Today `run` and `work` fail with
   `bind message supplies 2 parameters, but prepared statement "" requires 0` or
   `relation "_stage" already exists`, and tables stay `loading` until the pooler restarts. The program finds
   out before it claims anything (the cheapest test that is right, once per process, not per run) and stops
   with: a pooler in transaction mode, use session mode or connect directly. If no test is reliable, the two
   errors are recognised and given that reason, and nothing is left `loading` that the program can release.
   Needs a pgbouncer in the test harness: use an image only if it is small; otherwise test what can be
   tested without and say so here.
10. **The target restarted during a run**: the last line is ours (`connection to the target lost`), not
    Postgres's bare `FATAL: terminating connection due to administrator command` after it.
11. **The count `~N` of a run line and of the status is what it says it is.** After a dropped column and
    three changed rows it said `~60` (change-log rows). Read what the documents promise for the counts and
    make count and documents agree; a row the mirror did not get is not an update of the mirror.

### Documents

12. A `numeric(p,s)` widened to plain `numeric` reads without trailing zeros (`3.00` reads `3`; the values
    are equal): `docs/connectors.md` beside the other losses of a driver. The worker's grants: if a worker
    needs no `SELECT` on `_rowvioli.columns__log`, the documents and what `init` prints do not ask for it.
    A rename shows under the new name at every moment of the history view. What a change of columns costs
    in change-log rows, with H4's numbers (`docs/measurements.md` or `docs/target.md`). `CHANGELOG.md`.
    `.scratch/shakedown/eighth-run.md`: each line this ticket fixes is marked fixed.

## Acceptance criteria

- [ ] 1 to 11: a test each, seen red first, at the existing seam; a sentence here for any that cannot be
      tested there.
- [ ] The whole suite passes.

## Comments
