# 19: What the last review found

**Blocked by:** 18

**Model:** Opus

A last review before 0.5.0 found three faults, each ending `ok` with a wrong history, all where a primary key was
changed by hand and no record exists for the table under its target name. The red scripts are outside the repository,
in the session's scratch directory under `rv3/` (`test_c4_keys.py` cases `new-0.4.1` and `third-0.4.1`,
`test_c5_wayout.py` case `comment`).

## What to build

1. **A primary key changed by hand to the definition's new key on a table of 0.4.1.** Loaded by 0.4.1 under (k), no
   comment on `_op`, no record; the definition changes the key to (k2), and a person sets the primary key to (k2)
   before the first run of this version. Nothing fires, the run is `ok`, and the history at earlier moments is read
   under (k2), which was not unique then. `runs.definition` is a digest, so the old key is nowhere. Rule: for a table
   without a record, with a change log and no readable comment on `_op`, whose last successful run was under another
   definition, the change log must fit the definition's key where the primary key is it (the test `before_the_record`
   has: under a wrong key a key value has two rows at one moment, an `I` while it lives or a `U`/`D` while it does
   not). Where it does not, the run stops and asks for the comment on `_op` with the key it was written under; then
   the run changes the key as the definition would. No scan where the definition is the same.
2. **The same with a third key (k3).** `before_the_record` stops offering two comments, `[k2]` and `[k3]`, both false
   (the log was written under (k)); following the first gives `ok` with a wrong history. Where the change log fits
   neither key, the reason says so and gives item 1's way out; where it fits both, the reason stays.
3. **A mirror renamed by hand whose primary key was changed by hand to the definition's new key**, with no earlier
   change of key (`noted()` is None): the stop "names (…) last" offers a comment built from the definition's new key
   beside the old primary key; following the comment gives `ok` with a wrong history. Without a note, offer only the
   old primary key.

## Acceptance criteria

- [x] A test each, seen red first, its way out followed: history right at every earlier moment, replay = mirror.
- [x] No reason shows a value of a row.
- [x] An ordinary 0.4.1 table after the upgrade neither stops nor costs more than one gated scan.
- [x] docs/loading.md, decision 54 and the changelog say it.
- [x] The whole suite passes.

## Comments

Built on `sc-19` from `schema-changes` 4eecd7e (Opus, 2026-11-25), one commit per item, each test seen red first.

- 1: where no row of `_rowvioli.columns` has the table's id (before the record), with a change log and the primary
  key the definition's, `check` asks `before_the_record`: no scan where the definition is that of the last successful
  run, else one scan under the one key (in `long(...)`). Where the change log does not fit it: `the change log <t>__log
  was not written under (<key>), the key of the definition and of the mirror's primary key, so a person changed the
  primary key by hand before a run changed it: say the key it was written under, the key the table had when its
  change log was written, and the next run changes the key as the definition says: COMMENT ON COLUMN ..._op IS
  '[{"key": ["<the key column>"]}]'`. Before the record a readable comment on `_op` is what a person said (0.4.1 wrote
  none), so where its last key is not the definition's the plan is the change of key by the definition from it.
  Tested on a target of the released 0.4.1 (`tests/test_upgrade.py`), way out followed: mirror = source, primary key
  (k2), replay = mirror, history right at every earlier moment, a quiet run writes nothing. An ordinary 0.4.1 table
  (the existing upgrade tests) neither stops nor scans more than once: from that run on it has a record.
- 2: where the change log fits neither key, `the primary key of <t> is (k3), the definition's key is (k2), and the
  change log <t>__log was written under neither, so a person changed the primary key by hand before a run changed the
  key: ` and item 1's way out; where it fits both, the reason is as before. Followed in the same test: the run changes
  the key from the comment's (k) to (k2), and (k3) loses its primary key and NOT NULL as ticket 18 has it. Ticket
  14's test of a log that fits neither key (`tests/test_init.py`) asserted the two comments, each false there too;
  it now asserts this reason.
- 3: without a note (`noted()` None) the stop gives the old primary key alone; ticket 18's test now asserts it for
  both cases, with and without an earlier change of key, and follows it.
- No reason shows a value of a row.
- Not tested: a 0.4.1 mirror also renamed by hand (the same path, no record anywhere), and a composite or renamed key
  in items 1 and 2 (the comment's placeholder names one
  column; `renamed` is applied as for the other comments). The reviewer's scripts are not run as they are: their
  scenarios are the tests above, and `test_c4_keys.py` follows the old two comments.
- After review (sc-20): a comment naming (k1) of a composite key (k1, k2) was believed, and the run changed the key
  from (k1) to (k1, k2) with a wrong history. Where the comment's last key differs from the definition's, the run now
  scans the change log for two rows of one `_op` at one moment under it (in `long(...)`) and stops where it finds them:
  `the comment on column _op of the change log <t>__log names (k1) last, but the change log has several rows of one
  value of it at one moment, so it was not written under it: ` and the way out, whose placeholder is now
  `<each column of that key>` in all three reasons. Tested on a target of 0.4.1, seen red first, way out followed.

**Status:** resolved
