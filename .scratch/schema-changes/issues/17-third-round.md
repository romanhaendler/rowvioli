# 17: What the third round found

**Blocked by:** 15, 16

**Status:** claimed

**Model:** Opus

The third wave of the shakedown (2026-11-25, wheel of `sc-15` at 2583551): the personas that had not run, P1
beginner, P3 staff engineer, P4 vibe coder, P16 migrating team, P22 ELT specialist. Much of it is where no test
had been: the program moved onto tables it did not create, and a person changing the target by hand out of
habit. Each item starts from its red as a test at the existing seam; the scripts named are in the session's
scratch directory given in the task (they may be gone; each item says enough to build its red anew).

## What to build

### From ticket 16's review
- T1 a date of `±infinity` through psqlODBC arrives as the day of the run (the driver gives the raw text `0000-00-00`):
  today only documented. Check once more whether the connector can tell cheaply (only for columns described as
  date/timestamp, one comparison); if not, decision 55 holds it as the driver's loss.

### P1c beginner (scripts in scratchpad/shake/p1c)
- L1 Trap: after a wrong password a person fixes the environment variable and runs again; the same `password
  authentication failed` comes back and nothing says the connection is read when `apply` runs. A connect error of a
  source adds: the connection is as the last `apply` wrote it; after changing a variable run `apply` again.
- L2 Trap (made by ticket 14/15's withholding): a misspelt source table passes `apply`; the run says `a statement raised
  an error (SQLSTATE 42P01) in the source, reading public.customers2; its message may hold a row's values…`, never that
  the table may not exist. For 42P01/42703/42704/42883 a fixed sentence of the program's own that holds no value: an
  object the statement names does not exist (the table itself, a column, or one a view of it reads), and `rowvioli
  list <source>` shows the tables.
- L3 Leak, small: a password with `@`, `/`, `:` written into the URL unencoded (`postgresql://lena:p@ss/w:rd#1@host/db`)
  applies, and the run fails with `could not translate host name "ss" to address…`: a fragment of the password in the
  reason, and the wrong cause. `apply` refuses a URL that does not parse to what was meant (an `@` in what would be
  path, a port that is no number…), saying that a password with such characters goes into a variable or is
  percent-encoded. Find the smallest test that is right.
- L4 minor: `apply` in a directory whose `sources/` holds no file on a target with no tables says "applying it would
  disable every table": on an empty target say what to write (README).

### P4c vibe coder (scripts in scratchpad/shake/p4c: try.sh, rowvioli-bad/)
- J1 docs: `catalog` is explained only in `docs/connector-guide.md` (titled "A connector that needs licensed
  software"); `docs/connectors.md` (custom connector, the contract) and the README's "the whole contract is one
  function" never mention it, nor point from `driver_version` to it. One "contract" paragraph in connectors.md with the
  module-level names, linking the guide.
- J2 a connector's `driver_version` is stored as given: an int becomes "3", a text with a newline, 100,000 characters
  stored with every run. Refuse what is not a short one-line string (contract.py checks `catalog` already), with a
  reason naming the connector.
- J3 judge: a connector of one's own that delivers something odd gives raw library text (`precision should be between
  1 and 38`, `'list' object has no attribute 'schema'`, `Expected array with 2 buffer(s) but found 3`): the reason
  should say that the connector delivered what the contract does not allow (and name the connector), if one place
  (around the batch loop) can do it; the decimal case names the column (ticket 16 did it for Parquet).

### P16c migrating team (scratchpad/shake/p16c/REPRO.md)
- M1 Break (older): a consumer's foreign key onto a mirror fails every run that updates or deletes a referenced row
  (an update is DELETE then INSERT; a plain FK checks at once): `update or delete on table "orders" violates foreign
  key constraint "order_lines_order_no_fkey"`, stuck, no way out. `ALTER TABLE … ALTER CONSTRAINT … DEFERRABLE
  INITIALLY DEFERRED` loads (tried). The reason names the constraint's table and that way out (only where the
  violated FK points AT the mirror and the row is still there after the run, which the deferred check then
  proves); docs/target.md says it for updates, not only for a change of key.
- M2 Trap/Wrong: a table of the team's named `<t>__log` (no `_op`, `_run`) is taken for the change log: the stop says
  `column name of the mirror is not in the change log … DROP COLUMN "name"` (a source column!), and for
  `td__log(x int)` prints SQL that does not run and drops the key column. Likewise `<t>__history` that is a table
  (`SQLSTATE 42809` withheld), a team view `<t>__history` with other columns (42P16), a view named `<t>__log`
  (42703). One check before the first statement: an existing `<t>__log` / `<t>__history` that is not the program's
  (kind, `_op`/`_run`/`_loaded_at`) stops with: an object of this name is not rowvioli's, rename it or give the
  table another `target_table`.
- M3 Wrong: the source drops column `c`, a person drops `c` from the mirror by hand BEFORE the run: the change log
  gets no closing `U`s, so `<t>__history` shows the last values of `c` as current for good (100 rows `_valid_to is
  null and c is not null`), though `columns__log` records `U c by hand`. Without the hand drop it is right. The run
  writes the closing rows whenever a log column is in neither mirror nor source.
- M4 Trap: a type changed by hand on the mirror to another family while the source changed too: `SQLSTATE 42804`
  withheld (text into the int log column), no way out. A mirror column whose type differs from the change log's is
  seen before publishing and stops with the way out (`DROP COLUMN` on the mirror worked).
- M5 the stop `column segment is missing in the source; without a change log its values are nowhere else…` is also
  said for a table whose change log is only about to begin (first run onto an existing table with the team's own
  columns): wording must fit that case.
- M6 Misfit: adopting an existing table deletes the rows the source lacks without a word when under
  `max_delete_share` (`ok +0 ~0 -3`). Documented (target.md:23). Judge: is the first run onto a table the program
  did not create worth a line in docs/operation.md "moving onto existing tables" (and M1, M2 there too)? No new
  machinery.
- M7 the stop for a PK changed by hand in target and source and definition (`comment on column _op … names (id) last,
  where the change log is written under (id, a)`) does not name the cause (a key changed by hand before the run);
  the COMMENT it gives works. Add the cause to the sentence.

### P3c staff engineer (scratchpad/shake/p3c: chk.sh)
- E1 docs/target.md "Replaying it from its last change of key … gives the mirror, always": after a change of key a `D`
  (old key) and an `I` (new key) of the same run can meet on one key value (`(id)` -> `(n,id)`), same `_run` and
  `_loaded_at`; a replay ordered by those two cannot decide (2 rows off; right only with ctid). Say the order where
  the replay is described (within a run `D` before `I`), give the replay query in the documents in that order, and
  make the suite's replay helper use exactly the documented query (not ctid).
- E2 the reason "the definition has no key any more … drop the change log … with its history view … and the mirror"
  overstates: dropping the change log (and its view) alone was enough (`ok +11 ~0 -10`). Reason and docs/loading.md
  say the least that works; never tell a person to drop a mirror consumers read when it is not needed.
- E3 low: a very short password (`x`) masks every `x` in a reason (`ma***_delete_share`). Keep (safe side); say it in
  docs/connections.md in one sentence. The test harness's passwords should not be one letter if that is cheap to
  change (ticket 12 item 12 touched this).
- E4 README line 5 "Version 0.4.1" -> with the version bump (coordinator).

### P22c ELT specialist (scratchpad/shake/p22c: h.py, r1..r10.py; 65 cases, the rest held)
- G1 an array whose element type widens (`int[]` -> `bigint[]`) is another family (retired as `tags__<run>`, a `U` per
  row), unlike scalar `int` -> `bigint`; no document says how arrays are classed. An array's family is its element's
  (and it widens as its element does), if `family()`/`wider()` take it in a few lines and the fit test holds;
  otherwise docs/loading.md "A type" says it.
- G2 = L2, with the way out: for 42P01 on the table the program itself reads: the table may have been renamed or
  moved; change the table in the definition and keep `target_table` to keep mirror and history. (r6.py cases 36, 37)
- G3 docs/target.md:97-101 "the table as it was at a moment is one condition on the view": after a type of another
  family the values of earlier moments are under `<name>__<run>` (target.md:106 says it): one sentence beside the
  recipe.

### From ticket 15's review
- V1 the text offered to put back a lost comment on `_op` is the table's latest note in `_rowvioli.columns__log`,
  even one written for an earlier change log under the same id (a change log created again, an old target name):
  it could name stretches the new log never had. Scoping by target name alone would break a mirror renamed by
  hand. Find the rule that is right for both (e.g. only notes not older than the change log's first row, or
  checked against the log by `keys_of_log`), test both cases.
- V2 a withheld reason of an ODBC source says "the source's server log has it", which SQL Server does not keep by
  default: say "the source's server log or a trace has it" or what is true for every source.

## Acceptance criteria

- [ ] Every item: a test seen red first, or a sentence under Comments why none and what was done instead.
- [ ] Documents (`docs/*.md`, decision 54/55, `CHANGELOG.md`) say what changed; no new entry in
      `docs/open-points.md`.
- [ ] The whole suite and `tests/odbc/run.sh` pass.

## Comments
