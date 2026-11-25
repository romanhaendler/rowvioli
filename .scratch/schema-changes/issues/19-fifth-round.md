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

**Status:** resolved
