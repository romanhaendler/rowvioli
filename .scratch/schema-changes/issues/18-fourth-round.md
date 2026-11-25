# 18: What the final review found

**Blocked by:** 17

**Status:** resolved

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

- [x] 1 to 3: a test each, seen red first; 4: each lead red or shown not to occur.
- [x] The whole suite and `tests/odbc/run.sh` pass.

## Comments

Built on `sc-18b` from `schema-changes` 2a71d03 (Opus, 2026-11-25), one commit per item, each test seen red first;
`schema-changes` (db4ad54, with `sc-18`) merged in.

- 1, decided as the reviewer suggested, with one change in the closing pass: a column the record shows in the mirror
  (`mirror` true) and the mirror lacks is in `plan["closed"]` whether or not the source has it, under the name the run
  gives it (a retired one as `<name>__<run>`). The closing `U` is written for a row whose latest version in the change
  log differs from the mirror after the run: `IS DISTINCT FROM` the mirror's value where the column is back in the
  mirror, `IS NOT NULL` where it is not (as before). So a row the diff already wrote gets no second row at the same
  moment, and replay and history stay right. The source's values come against an empty column, so every row with a
  value gets a `U` once (the mirror must be filled anyway). Tested (8 cases, history at every moment, replay, mirror =
  source, a third run writes nothing): type changed by hand then dropped with the source's value set to null, changed,
  unchanged, the source in another family too; dropped by hand with no source change and with a null; and a table
  without a record.
- 1, a table without a record (before version 4; tested by deleting its rows of `_rowvioli.columns`): its first run
  takes every column the change log has and the mirror lacks as closed. The pass writes only where a value is still
  current, so a column that went properly costs one pass over the change log and no row; a column 0.4.1 left current
  after a drop by hand is closed at that run. Not wrong in silence, and no stop needed. From then on the record holds.
- 2, the run handles the state: where the mirror's primary key is the definition's and the record's key (this target
  name's) is another, a person changed it to the definition's new key before a run did; the plan is the ordinary
  change of key by the definition, from the recorded key (stretch, `D`/`I`, primary key added after the rows). This
  also covers ticket 17's M7 case, whose way out gave a comment naming a key the change log was never written under
  (wrong history once a key value had changed before); its test is replaced by this one (with and without an earlier
  change of key, history at every moment). Without a record under the target name (a mirror renamed by hand in the
  same breath) the stop stays; docs/loading.md says to put the old primary key back there. Not tested: that triple case.
- 3: `key column <k> is missing in the mirror <t>, dropped by hand, so its rows cannot be told apart: give the table
  another target_table, which begins a new mirror`, followed in the test (with and without a record). Checked where the
  diff would join by the key (not for a change of key by the definition, which replaces the mirror). Not tested: an old
  key column dropped by hand in the run that changes the key by the definition.
- 4a red, fixed: `noted()` takes this target name's latest note first, any other's only where it has none. 4b red,
  fixed: an old target name's retired note counts only for a column this target name has not recorded. 4c reproduced
  (scratch test, not kept: a person holds `SHARE ROW EXCLUSIVE`, deletes the row while the run waits in its `DELETE`):
  run `ok` with `updated 0`, the `U` stands, the next run writes an `I`. The lock does not rule it out (taken after the
  diff, and only for a change of columns). Not fixed: it is the same change log as a delete by hand right after the
  run, and decision 54 holds the mirror's rows as the program's; said there.
- 5: README.
- No new reason shows a value (item 3 names a column and the table).
- The reviewer's scripts against this branch: `test_handdrop.py`, `test_combos*.py` pass; `test_stops.py` and
  `test_combos2.py::test_key_column_dropped_from_mirror_by_hand` fail as they should now (they asserted the old stop,
  and an `ok` for item 3).

Suites at the tip (after merging schema-changes db4ad54), on fresh containers: the whole suite 900 passed, 24 skipped
(8 min 15 s); `tests/odbc/run.sh` 20 passed, 1 skipped.

### Review (Opus, 2026-11-25, on `sc-18b-review` from `sc-18b` 1e3850d)

Each fix of items 1 to 4 taken out: its test red (item 1: 5 of its 8 cases; item 2: both; item 3: both; 4a and 4b of
item 4: red), put back: green. Item 1 tried on a database (scratch tests, not kept): a retired column `c__<run>` with
and without a record, then quiet runs; a column gone by the source's drop that comes back in its family, in another,
or never, with and without a record; a renamed column then dropped by hand; a mirror renamed by hand with a retired
and a gone column (no record under the new name), then a drop by hand; `log = false` and back; a change of key by the
definition in the run with a drop by hand; two quiet runs. After each: mirror = source, replay = mirror, history at
every earlier moment = the snapshot, later runs write no row. All held. Item 2: composite keys, the same columns in
another order, from and to composite keys, a key changed by hand to another than the definition's (put back): held.
Faults found, each fixed test-first, one commit each:

- **A primary key changed by hand to a third key while the definition changed it** (ae1100b): the plan took the
  person's key for the one the change log was written under, so the run stopped with a comment naming it, and
  following it made the history partition by a key the log was never written under; the person's key also kept NOT
  NULL in the mirror. Now the change goes from the recorded key (or, without a record, the comment's last), and the
  person's columns lose NOT NULL too.
- **4b, an old key column dropped by hand in the run that changes the key by the definition** (9e9e199): the `D` rows
  had a null in the old key, and the run failed on the change log's NOT NULL with no way out. Now it stops with item
  3's reason, whose way out (another `target_table`) is followed in the test.
- **4a** (ddc7631): without a record under the target name, where the mirror's primary key is the definition's, the
  reason gives `ALTER TABLE ... DROP CONSTRAINT ..., ADD PRIMARY KEY (<the comment's last key>)`; where the comment is
  not the program's last note it gives both statements. Followed in the test, history right at every moment.
- **4c** (a976712): a cheap exact fix exists. The `I` insert also takes a `U` whose row is gone from the mirror
  (`NOT EXISTS` by the key): no delete and insert of a changed row, and a row kept for a column that went is in the
  mirror, so it is not touched. Counted as updated. Tested with and without a column that goes. Decision 54 says it.
- **A 0.4.1 change log upgraded** (a74a561): where a person dropped a column under 0.4.1 that the source kept, 0.4.1
  added it again and left a value that had become null current in the change log. The first run without a record
  now closes every column of the change log that differs from the mirror (key columns, the join's, excepted). And a
  closing alone took the lock of a change of columns and dropped the history view, so a consumer's view on it
  stopped the run, also for a drop by hand with a record; now closing writes rows alone. Tested on a target of the
  released 0.4.1 (`tests/test_upgrade.py`).

Every reason this ticket added or changed names columns, keys, tables and a constraint, never a value of a row, and
says its way out. Not checked: a primary key changed by hand to a third key on a 0.4.1 change log without a comment
(before_the_record), and a mirror renamed by hand while its key is changed by hand to a third key.

Suites at a74a561 on fresh containers: the whole suite 909 passed, 24 skipped (8 min 39 s), no failure;
`tests/odbc/run.sh` 20 passed, 1 skipped.
