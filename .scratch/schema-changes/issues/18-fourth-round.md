# 18: What the final review found

**Blocked by:** 17

**Status:** ready-for-agent

**Model:** Opus

A fresh review of the branch as it is (2026-11-25, at 1fdb4b3) found three faults with a red script each, and three
leads. The scripts are outside the repository, in the session's scratch directory under `rv/` (test_handdrop.py,
test_stops.py, test_combos2.py). Each starts from its red as a test at the existing seam.

## What to build

1. **A column the change log has, the mirror lacks and the source still delivers is closed in the change log before
   it comes again** (wrong result with the run `ok`, reached by the program's own way out). A person changes the
   mirror's `c` to another family; the run stops with "drop it from the mirror and the next run brings it again";
   the source sets `c` to null for a row; the person drops the column; the next run is `ok`, and the change log's
   latest row for that key still says the old value: its replay is not the mirror. The diff compares such a column
   against null, not against the change log's latest value. Second form: the source changed `c` to another family
   too; the retired `c__<run>` then keeps its values as the current version in the history view, where a column
   that is retired by a run gets its closing `U`. Any drop by hand of a column the source keeps does the same.
   Ticket 17 (M3) closes such a column only when the source dropped it too. One rule: a column the record shows in
   the mirror and the mirror now lacks is closed, whether or not the source still has it, and what the source
   delivers then comes as a column that comes back. Replay equals mirror, and the history at every earlier moment
   is right, in both forms and for a table recorded before version 4 if that case differs.
2. **The stop for a comment on `_op` that names another key last leads out** when its cause is the second one it
   names: key `k` to `a` by the definition, then the definition says `b` and a person changes the mirror's primary
   key to `(b)` before the next run. The text to put back is the comment that is there already, so following it
   changes nothing. Either the run handles the state (the key was changed by hand to the definition's: nothing to
   put back, it goes on as for a key changed by the definition, if the history stays right), or the reason says
   the way that works (put the old primary key back, with the statement). `docs/loading.md` then says the truth.
3. **A key column dropped from the mirror by hand** stops with a reason that says what happened and the way out,
   instead of `a statement raised an error (SQLSTATE 42703) in the target`.
4. Leads, each reproduced first; fixed if red, a sentence under Comments if not:
   - `noted()` across target names A to B to A: a key change under B gives a note no older than A's change log's
     first row; with A's comment lost the stop would hand out B's stretches.
   - the check of a retired column's comment reads notes "also under an old target name": a source column under the
     new target named like an old target's retired column (`c__5`) would be told to take that comment.
   - a person deletes a row of the mirror between diff and publish: the in-place update changes no row, the change
     log says `U`, the run is `ok`. Check whether the run's lock on the mirror rules it out; if it does, say where.
5. README: "A worker takes the most overdue table" leaves out that a table never tried goes first (decision 55).

## Acceptance criteria

- [ ] 1 to 3: a test each, seen red first; 4: each lead red or shown not to occur.
- [ ] The whole suite and `tests/odbc/run.sh` pass.
