# 10: The findings of the review of the whole branch

**Blocked by:** 07, 09

**Status:** claimed

**Model:** Opus

Spec: `.scratch/schema-changes/spec.md`; the tickets beside this one; decision 54 in `docs/decisions.md`. Two reviews read the whole branch (`git diff 708f748...schema-changes`), one against the spec with probe runs, one against the repo's standards. Line numbers are those of `src/rowvioli/load.py` at a8164cc.

## What to build

### Wrong (each confirmed by a probe run)

1. **The second way out of the "not in the change log" stop loses a person's values** (`load.py:152-153`). A person follows "or add it to the change log too and the next run takes it out of the mirror": the next run drops the column and writes a `U` per row with it empty; the values are nowhere. The reason gives the same way out as the branch above it (the copy with `CREATE TABLE … AS SELECT`, then the drop) and nothing that loses values. Ticket 09: "A mirror column that the change log does not have is never written by a run."
2. **The first run after an upgrade records what it did as `found` and notifies nobody** (`load.py:722`, `:765`). A version 3 target, `init`, the source drops `city`: `columns__log` has only `I city mirror=false by=found`, no notification; the same for a type of another family (`a__2 … by=found`). On a first fill, `found` is only for columns the run neither changed nor has in `changes`; the rest get what they would get otherwise (`source`, `definition`, `reader`), which also sends the notification (decisions 16, 19; story 45). The test builds a target as the released version leaves it (`version_3()` in `tests/test_init.py`, no comment on `_op`, no rows in the columns table), not a target the new program already filled.
3. **A mirror type widened by hand stops with Postgres's bare message when a consumer's object depends on the history view** (`follow()`, `load.py:686-688`): no object named, no way out, and it waits for a lock while holding one (story 43). It goes through `alter()` (decision 15) and under the `NOWAIT` lock: the hand-widening becomes part of the plan.

### Missing

4. **`cases.md` A20** (story 10): a delivered column name over 63 bytes fails the run and names the column; two names that are equal in their first 63 bytes fail and name both. In `stage()`, before anything is written. The tests of ticket 01 that pin the silent cut are changed to this.
5. **Tests named after `cases.md` D6 (story 41: a view on a history view stops a change of any column and is named), G6 and H3**, or a sentence in this ticket why not. The behaviour is there.

### Against the repo's standards

6. **New tests import the program** (`tests/test_file.py:12` and `:373`, the test added to `tests/test_reason.py:38`): both cases go through `rv.run` and assert the reason in `status` (spec "Testing Decisions").
7. **"decision N" in new comments means the spec's item, where the code's older comments mean `docs/decisions.md`** (`load.py:263`, `:353`, `:506`, `:584`, `work.py:193`, the connectors' "decision 11", `target.py` "decision 24"): they cite decision 54, or say the thing without a number.
8. **File tables are told from Parquet by a regex on the table's name** (`load.py:166`) that repeats `file.READERS` and misses patterns such as `orders_*` or `*.csv.gz`. The file connector says whether a column's type is the file's own; one list.
9. **The `columns` pairs are turned into a dict in three places** (`load.py:165`, `:356-357`, `:732`) and only `stage()` checks the shape: a connector of one's own with a list under `columns` makes every run raise in `record_columns`. Once, in one place.
10. **Hiding a value depends on the driver's wording** (`postgres._cast` tests for `"is not a valid"`, `file.uncast` for `startswith("Conversion Error")`): any error of the cast gives the reason that names the column, so a changed message cannot show a value (decision 54, item 8).

### Small, only where it changes no behaviour

11. `plan["retired"] | {o: n for n, o in plan["renamed"].items()}` twice (`:454`, `:555`; variants `:131`, `:254`); the test whether `renamed` applies twice (`:91-92`, `:121-122`); a literal quoted by hand three times (`:223`, `:618`, `:660`); `way` and `drop` bound twice in `check()`; `changes` rebound from a dict to a string (`:753`); two stops for one rule in `check()` (`:201-205`, `:213-216`); `MIGRATIONS` and `GRANTS` in `target.py` kept in step by index. Take what is a few lines each; leave the rest. No rebuilding of `check()` or `publish()`.

### Documents

12. `docs/loading.md` (the stops table), `docs/open-points.md`, `cases.md` and decision 54 say what is true after 1 to 5 and 8.

## Acceptance criteria

- [ ] 1 to 5: a test each, seen red first, at the existing seam; the replay invariant where columns change.
- [ ] 6 to 10: the existing tests pass, moved to the seam where 6 asks; a test for 8 (a pattern without an extension) and 9.
- [ ] The whole suite passes.

## Comments

Implementer (branch `sc-10`), what is not done or not tested:

- Item 5: the tests of D6, G6 and H3 passed at their first run, since the behaviour was there; none was seen red.
- Item 10 has no new test, since the ticket asks for none: the path a changed message takes (Arrow's `The string '1.5e400' cannot be represented as decimal256`, which before kept its value) is not run at the seam.
- Item 4 is tested with a CSV only; a REST source takes the same check in `stage()`. A Postgres source cuts a long name itself, so `tests/test_run.py` keeps its test of that, renamed.
- Item 3: a log column followed after a widening by hand is altered under the reason `... would be widened for values of the source`, the text the source's widenings have; only a consumer's view on that log column would show it.
- Item 11, left: the `moved` dicts (the one in `check()` is taken before the proofs, so it is not the same dict, and a helper for two uses saves nothing); the `renamed` test in `load()` and `check()` (their conditions differ, and merging moves code between them); the two stops of `check()` for one rule (merging changes a reason). Done: a literal quoted in one place, `way` and `drop` bound once, `payload`, and `MIGRATIONS` carrying their grants.
- Item 7 covered `src/`; `tests/test_types.py` still has a comment `# decision 20` meaning the spec's item.
- Found on the way, not in this ticket: a run reads and deletes the rows of a consumer's child table of a mirror (`CREATE TABLE ... () INHERITS (mirror)`): the diff and the publish read the mirror without `ONLY`, so the child's rows are `D` in the change log and gone (seen in a probe run). `cases.md` G6 says only that a gone column leaves the children.
