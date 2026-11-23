# 07: A run publishes into a target name that `apply` gave to another table meanwhile

**Status:** resolved

**Model:** Opus

From the whole-program read of 0.4.0 (`.scratch/shakedown/sixth-run.md`). Confirmed in the source by the coordinating session; the outcome is not yet reproduced.

## What is wrong

The table lock guards a table id (`pg_advisory_lock(source_id, id)` in `load.py`, the claim). A run reads its target name at the claim and never looks again. `apply` checks that no two tables of the new definition take one target name, and renames or disables rows whatever is loading (`sql/apply.sql`; its comment and decision 46 say a table loading under the old name "publishes into the old mirror").

Path: table A loads into `raw.x`. An `apply` gives `raw.x` to table B (two tables swap `target_table`, or a source table is replaced by another one that keeps the target name). B is new, so due at once, and loads under another lock. A then publishes its diff, or without a key its whole staging table, into what is now B's mirror, with status `ok`, until B's next run repairs it.

## What to build

1. First a test that shows it through real processes (a slow source for A so that the `apply` and B's load fit into A's run), red on 0.4.0. If it cannot be made red, say why and stop: then the ticket is the comment and decision 46 only.
2. The smallest change that makes "never two runs on one target table" true by name: the publish transaction first proves that the run still owns its target name (its row still has this `target_schema`, `target_table` and is enabled) and fails the run with a reason a person understands otherwise. Nothing is published then.
3. Decision 46 and the comment in `sql/apply.sql` say what is now true, in the way decisions were changed before.

## Acceptance criteria

- [ ] The test from 1 is green; the mirror of B holds only B.
- [ ] A rename with no new owner behaves as decision 46 decides after the change, and a test says which way.
- [ ] `tests/test_apply.py`, `tests/test_run.py`, `tests/test_work.py`, `tests/test_crashes.py` green.

## Comments

Reachable and reproduced on 0.4.0: `apply` disables the old table (replaced) or renames it (swap), the new owner is new and due at once under its own lock, and the old run publishes after it with `ok`; `test_run.py` holds the old run at its source read with a lock in the source. The last statement of the publishing transaction now sets `loaded_at` only where the row is enabled and has the run's name, else the run fails and nothing is published; its row lock makes a later `apply` wait until COMMIT, and an earlier one is seen. A rename with no new owner fails the same way and its next run loads the new name at once (decision 53, which changes 46). Not done: a run whose writes fail first on the new owner's mirror gives that error instead of the reason.
