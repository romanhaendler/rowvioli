# 15: After the review of part two: an upgrade from 0.1.0 costs nothing and says what changes

**Blocked by:** none

**Status:** resolved

**Model:** Opus

From the review of `out-of-the-box..part-2` on 2026-11-17. CONFIRMED findings were seen to go wrong there;
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

- [x] An unchanged run on a 0.1.0 mirror of 300 `numeric(12,2)` columns takes about what a mirror of the new program takes (measure both, same machine, same minute).
- [x] `numeric(3,5)` from a Postgres 16 source loads into a Postgres 14 target.
- [x] After a target restart during a load, the log, `runs` and `rowvioli status` give the same reason.
- [x] The Try-it block works pasted into `zsh -f -i`, and a second time.
- [x] `tests/test_numeric.py`, `tests/test_crashes.py`, `tests/test_work.py`, `tests/test_try_it.py` pass; the whole suite once at the end, alone.

## Comments

2026-11-17, Opus. Changed: `load.py` (`fit()`, a new `misfit()`, the staging lines in `stage()`, the closing line
in `claim()`), `work.py` (`end_lost()`, `record()`, one line in `listen()`), the README, the changelog, decision 49,
the open points, tests.

### 1. A 0.1.0 mirror costs what a new one costs

300 columns of `numeric(12,2)`, 20,000 rows, unchanged runs on this machine, the part-2 code and the fix
one after the other on the same two mirrors. The 0.1.0 mirror was built as in the test: made by the new program,
then the mirror and its log altered back to `numeric`.

| Code | 0.1.0 mirror (`numeric`) | mirror of the new program (`numeric(12,2)`) |
|---|---|---|
| part-2 | 33.5 s, 32.0 s | 7.9 s, 8.1 s |
| now | 4.6 s, 5.0 s | 4.7 s, 4.6 s |

There were three costs, not one. The reviewer's two scans per column were one. The other two were `ALTER TABLE`
on the staging table: even empty and without a rewrite, an ALTER of 300 columns takes 3.5 s (measured in psql,
with 0 and with 2,000 rows; the filenode stayed the same). `CREATE TEMP TABLE ... AS SELECT` with the casts takes
5 ms. So:

- `stage()` has the driver create its empty table as `_driver` when there are decimals, then creates `_stage` AS
  SELECT with a cast per `decimal128` column. The driver creates no NOT NULL, so nothing is lost by `AS SELECT`.
- `fit()` no longer alters the staging table at all. A staged column that differs from the mirror only in its
  modifier is counted in the mirror's type in the list it returns. Numbers compare equal whatever their modifier,
  and the mirror's type applies on insert, where `misfit()` has made sure it changes no value.
- One query asks Postgres, for all such columns at once, whether the types are the same apart from the modifier
  and whether the target has a modifier. A target without one (`numeric`) needs no check. The others are checked
  in one scan of the staging table. A value too large raises in that scan; then column by column finds which one.
  The message is the same as before.

### 2. A scale outside 0 to the precision stays numeric

Decided without asking the server version: `0 <= scale <= precision` holds on every version. `numeric(3,5)` and
`numeric(5,-2)` now arrive as `numeric`. Tested in the suite (`test_numeric.py`, red before). By hand from a
PG 16 source into a `postgres:14-alpine` target (removed afterwards): `a numeric, b numeric, c numeric(12,2)`,
values `0.00123 | 12300 | 137.00`, and a second run with no change.

### 3. Closing a dead run's row

`WHERE run = (SELECT max(run) FROM runs WHERE "table" = $1) AND status = 'running'`: a backward scan of the
primary key that stops at the table's newest run. Measured on 200,000 runs: 7.7 to 8.7 ms before. After, it was
0.4 ms for a recent table, 1.3 ms when 24,000 runs had come since, and 11.4 ms in the worst case, a newest run
200,000 rows back. An index on `(table, run)` would bound it, but it needs a schema migration, which is not built.
Recorded in the open points.

### 4. A lost target connection is recorded

- `end_lost()` writes the reason before it kills the run. The run's lock is gone, so it cannot publish any more.
- A run that answers `connection to the target lost` itself (the server process was killed) is recorded at the
  top of the next loop, as a run ended after `max_seconds` is.
- Tests:
  - The restart test now waits for `runs` and checks the status: both say `connection to the target lost`.
    Red before: it timed out on `worker lost`.
  - `test_a_run_whose_server_process_is_killed_fails_and_run_says_so` expected `worker lost`; it now expects
    the worker's reason in the status and in `runs`.

### 5. A max_seconds reason replaced by worker lost: it can happen

From reading the code: the worker kills the run, its lock goes, and the worker writes the reason a few ms later, at
the top of its next loop. If the table is due at that moment, another worker's claim in between closes the row as
`worker lost`. The worker's `record()` then found no `running` row and wrote nothing. The table is due when
`max_seconds` is longer than the pause after a failure, or a request came during the run. I did not race two
workers; the test does what the claim does, by SQL while the run is loading, and was red (`worker lost`). The
fix is small: `record()` also replaces a `worker lost` on that run's row, keeping its `finished_at`. It sets the
table's reason only when the row was still `running`, because otherwise the table belongs to the new claim's run.
The README's "Order when finishing" says so.

### 6. Try it in a minute

- The block has no comments; what they said is in the text before it.
- `test -f worker.key || rowvioli key new` stands on its own line, so a second paste keeps the key.
- `cd ..` ends the block, so a second paste starts where the first did.
- The test asserts that the block holds no `#`. It now also runs the block a second time in the same directory
  against a second database.
- Pasted twice into `env -i ... zsh -f -i` (a throwaway venv with this branch installed, so `pip install` changed
  nothing): both times `3 inserted, 0 updated`, then `1 inserted, 1 updated`, and the history with five rows.
  `rowvioli-try` was gone afterwards.

### 7. The changelog

- "Changed" now opens with: update every worker before applying new tables, what a 0.1.0 worker says, and the
  ALTER for going back.
- A 0.1.0 mirror's two forms of a number.
- An unknown option at the source fails every table of the source.
- The typo check has moved from "Added" to "Changed".
- The negative scale arrives as `numeric`.
- Item 4 and 5 are under "Fixed".
- The README's "Deploying while loads are running" says the worker order once.

### Left

- The worst case of item 3 (above).
- A real race of two workers for item 5.
- A paste with no pause between the first block's `docker stop` and the second's `docker run`; I waited 4 s.
