# 11: The findings of the shakedown before the merge

**Blocked by:** 10

**Status:** ready-for-agent

**Model:** Opus

The record: `.scratch/shakedown/eighth-run.md`. The agents' repro scripts are in the session's scratch
directory named in the task (they may be gone; each finding is described well enough to build its red anew).
A fix starts from the host's red as its first test (`docs/agents/shakedown/README.md`).

## What to build

### Wrong

1. **A primary key changed by hand before the upgrade is put back, and the history stays right.** On a
   target from 0.4.1 (no rows in `_rowvioli.columns`, no comment on `_op`), a mirror whose primary key a
   person changed to `(id, v)` while the definition says `(id)`: today the first run takes `(id, v)` for the
   change log's former key, writes a `D` and an `I` per row, records `by = definition`, and the history view
   at a moment before the upgrade gives too many rows (`load.py:208-211`). It must tell this from a key
   changed in the definition on 0.4.1 (which also has no record, and must keep resolving by itself, story
   45) without guessing: by what the target holds (the definition a table's last successful run loaded
   under, `_rowvioli.runs.definition`, if that says it for the table; otherwise by the change log itself,
   which was written under exactly one of the two keys: under the wrong one it has an `U` or `D` for a row
   that key never saw, or two live rows for one key). If neither can tell, the run stops with a reason that
   says which statement settles it (story 22: the program never guesses what identifies a row). Tests: both
   tables built as 0.4.1 leaves them (`version_3()` in `tests/test_init.py`), the history at a moment before
   the upgrade, the replay, the record (`by = hand`).
2. **A history view keeps the grants it had when a run builds it anew.** The run drops and creates it
   (`load.py:563`, `:696`) where 0.4.1 replaced it; a grant given by name is lost. Read the view's grants
   before the drop and give them again after the create, in the same transaction; the owner stays. Test: a
   role granted by name reads the history view after a dropped column, a change of key and a rename.
3. **`renamed` onto a name the program keeps for itself is refused by `apply`** (`_op`, `_run`,
   `_loaded_at`, `_valid_from`, `_valid_to`), and a run meeting it (a definition applied by an older
   program, or a source column of that name) stops with a reason that never tells a person to rename the
   change log's own column (`load.py:121-133`).
4. **The retired name that is taken** (`<name>__<run>` meets a real column): reproduce it first (H2: a
   source with `amt` and `amt__2`, `amt` changes its family in run 2). The next run passes untouched because
   its number is another; following the reason leads into a second stop and cuts the old values off. Either
   the run takes the next free name by itself, or the reason says to run again; no way out that damages.

### Reasons

5. `permission denied for table columns` / `columns__log` in a run: the reason adds that the worker's role
   lacks a right on the columns table and that `rowvioli init` prints the grants on the upgrade
   (`docs/operation.md`). `the target has schema version 3, this program works with version 4` adds
   `rowvioli init` brings it to 4 (only in that direction).
6. A `numeric` with more than 38 digits is not "such as NaN or Infinity": the reason says which.
7. A REST column whose type does not match the answer (`column amt is not text`) says the way out as the
   file connector's does; `_op cannot be freed` says what a person does (a view of the source that names it
   otherwise).
8. A newline or other control character in a column's name does not cut a reason: it is written as `?`, as
   the messages a command stops with do.
9. A comment on `_op` that is not what the program wrote (a key that is no list, a `from` that is no
   moment, a column that does not exist) stops with the reason the missing comment has, with the text to
   put back, instead of Postgres's message.

### Documents

10. `docs/target.md`: the queries an auditor is given work with `SELECT` on `columns__history` alone (the
    "what changed, and why" query and the listener's recipe do not read `columns__log`; if the view lacks a
    column for that, `_run` and `_op` are in it or are added to it in the version 4 step, which is not
    released); a prepared statement fails until it is prepared again, also after a widened type; a reader
    that lists columns and then selects them reads again when a column is gone; who may read
    `columns__history` reads the columns, indexes and grants of every schema; a rename shows under the new
    name in the history view at every moment, and `was` joins it with the columns table.
    `docs/operation.md`: stop every old worker before `init`, and what a forgotten one does (a line a
    dozen times a second, nothing damaged); grants on a history view. `docs/loading.md`, `docs/connectors.md`,
    `docs/open-points.md`: what 1 to 9 change; a `numeric` widened to plain `numeric` reads without trailing
    zeros; a file column that is gone from the header stays, empty, and how a person removes it; the
    findings marked "left" in the record that are limits of this feature. `CHANGELOG.md`.
11. `docs/agents/shakedown/personas.md`: a host "Upgrade from the released version" in the manner of the
    others, with `Run: 2026-11-24` on it and on H1, H2, H4, P18, P20. `brief.md`: end only processes you
    started, by their PID.

## Acceptance criteria

- [ ] 1 to 4: a test each, seen red first, at the existing seam; the replay invariant and the history at an
      earlier moment where they apply.
- [ ] 5 to 9: a test each where the seam reaches it.
- [ ] The whole suite passes.

## Comments
