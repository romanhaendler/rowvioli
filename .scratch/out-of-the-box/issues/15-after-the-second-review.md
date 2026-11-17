# 15: After the review of part two: an upgrade from 0.1.0 costs nothing and says what changes

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Opus

From the review of `out-of-the-box..part-2` on 2026-11-18. CONFIRMED findings were seen to go wrong there;
each fix starts from its red test all the same.

## What to build

1. **A mirror made by 0.1.0 pays two scans of the staging table per numeric column on every run**
   (`fit()` in `load.py`): 300 columns of `numeric(12,2)`, 20,000 rows, unchanged run: 12.7 s with 0.1.0,
   47 to 49 s now; a mirror the new program made itself: 13 to 14 s. A cast to a type without a modifier
   changes no value, so nothing needs to be looked up there; and where values must be checked, one scan of
   the table checks every column. The time of an unchanged run on a 0.1.0 mirror is that of 0.1.0 again.
2. **A scale above the precision or below zero on a target older than Postgres 15** (`numeric(3,5)`,
   `0.00123`): loaded with 0.1.0, fails now in the ALTER of the staging table. Such a column stays `numeric`
   unless the target can hold the type.
3. **Closing a dead run's row scans all of `_rowvioli.runs` in every claim, under the lock all claims
   share** (18 ms at 200,000 rows, growing with a table that only grows). Only the table's newest run can be
   the dead one: look at that row alone.
4. **A run the worker ends because its target connection is lost is logged as `connection to the target
   lost` and recorded as `worker lost`.** The worker has a live connection then: record the reason the way
   it does for `max_seconds`, so that the log, `runs` and the status say the same.
5. **A reason of `max_seconds` can be replaced by `worker lost`** (read, not run): the worker records the
   reason at the top of its next loop, and a claim by another worker in between closes the row first. Find
   out whether it happens; fix it if the fix is small (the row is closed by whoever knows the reason), else
   record it as a known limit.
6. **"Try it in a minute" in the README**: two lines end in a comment after the command, which an
   interactive zsh (the default shell on macOS) passes as arguments: `rowvioli run try   # ...` fails and
   `docker stop rowvioli-try   # ...` leaves the container running. Run a second time from the same
   directory, `key new` refuses and the chain stops. Comments on lines of their own; a second run works.
   `tests/test_try_it.py` runs the block with `bash -e` and cannot see the first: make it see it (run the
   block as an interactive zsh would read it, or assert that no command line of the block carries a comment)
   in the smallest way.
7. **The changelog under "Unreleased"** says everything a user of 0.1.0 can notice:
   - workers of 0.1.0 and of the new version cannot share a target: a mirror a new worker creates with
     `numeric(p,s)` fails under an old one (`has changed its type from numeric(10,2) to numeric`), and
     "Deploying while loads are running" in the README restarts workers one at a time. Say it there and in
     the changelog: update every worker before applying new tables; going back to 0.1.0 needs
     `ALTER ... TYPE numeric` for such columns.
   - a 0.1.0 mirror keeps `numeric`, so rows loaded before and after show the same number in two forms
     (`137` and `5.50`); they compare equal.
   - an option at the source that a shipped connector does not know fails every table of it, not only a
     table's own option.
   - under "Changed", not "Added": a `type` one letter from a shipped connector's name fails `apply` unless
     a connector of that name is installed there; the typo check covers settings of three letters or fewer and
     counts two swapped letters as one.

## Acceptance criteria

- [ ] An unchanged run on a 0.1.0 mirror of 300 `numeric(12,2)` columns takes about what a mirror of the new program takes (measure both, same machine, same minute).
- [ ] `numeric(3,5)` from a Postgres 16 source loads into a Postgres 14 target.
- [ ] After a target restart during a load, the log, `runs` and `rowvioli status` give the same reason.
- [ ] The Try-it block works pasted into `zsh -f -i`, and a second time.
- [ ] `tests/test_numeric.py`, `tests/test_crashes.py`, `tests/test_work.py`, `tests/test_try_it.py` pass; the whole suite once at the end, alone.

## Comments
