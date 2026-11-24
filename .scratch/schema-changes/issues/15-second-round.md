# 15: What the second round found

**Blocked by:** 14

**Status:** claimed

**Model:** Opus

The second whole-branch review (spec, standards, a hunt for faults against a real database), the coordinating
session's own reading and the second wave of the shakedown, on c917551. Each item starts from its red as a test
at the existing seam; the scripts named are in the session's scratch directory given in the task (they may be
gone; each item says enough to build its red anew). Items marked "from the code" are reproduced first. Later
reports of the wave are added below as they arrive.

## What to build

### Own reading (confirmed against postgres:16)
- O1 Leak: class 42 is shown but 42601 can hold a row's value: `to_tsquery(col)` -> `no operand in tsquery: "SECRET4711 &"`;
  `'SECRET 4711'::regtype` -> `syntax error at or near "4711"`; `'a.b.c.SECRET.e'::regclass` -> `improper relation
  name (too many dotted names): a.b.c.secret.e`. 42602 `invalid name syntax` is of the same origin. Rule wanted: of
  class 42 only codes whose message cannot embed a runtime string (at least 42501); prefer the allowlist.

### Standards review (Opus)
- S1 `tests/test_odbc.py:213` imports the program (`without_value`); conftest says tests never import it.
- S2 `widen()` (load.py:1020) adds columns while `plan["widen"]` widens types: rename the function.
- S3 comment load.py:185 "fit() did the same" is no longer true (check runs first).
- S4 decision 17's "Changed by" note for 55 sits after Price (docs/decisions.md:225), others at top; stray blank line
  in decision 55's list.
- S5 lock_timeout: widen() leaves 10s for the rest of the transaction, so the decision-53 UPDATE of a run that added a
  column fails after 10 s with 55P03 instead of waiting for apply; and widen's 10 s wait happens while holding the
  mirror's ACCESS EXCLUSIVE (story 43). One rule: bound exactly the statement, 50ms as alter(), reset after.
- S6 nits: `way =(`, `names =",`, check() docstring line break, KEYS_NOTE comment spill (load.py:751), file.py:7 and
  contract.py:5 overlong docstring lines, `long :=` shadows `long()` (load.py:225, 455), `key` bool (load.py:111),
  `x` (load.py:1001); inverse-rename dict built four times; retired-note decode twice (load.py:266, 958).
- S7 `connectors/postgres.py:23` reads private `cur._results.reader` with unbounded `adbc-driver-postgresql>=1.13`:
  pin an upper bound or guard with a test that fails loudly.
- S8 `tests/test_columns_go_and_come.py:579` sleeps 1 s where a condition could be waited for.

### Spec review (Opus)
- P1 stops without a way out: `a key column of (…) is null`, `a key combination of (…) occurs twice` (load.py:272-275),
  `table X has no column k; it has: …` (load.py:462-464). Decision 54 + story 47: every stop says the way out. Also
  docs/loading.md "The rest of the stops" and decision 54 "Where it stops".
- P2 CONFIRMED red: mirror and change log with a `json` column from before, source delivers jsonb: plan retires `j`,
  diff() compares `ROW(…, NULL::json) IS DISTINCT FROM ROW(…, m.j)`, json has no equality -> 42883 withheld, stuck for
  good. docs/connectors.md promises it goes and comes as jsonb. `json[]` too. Must go and come.
- P3 CONFIRMED red: change log exists, `log = false` applied (or key taken away), source drops `city`: first run says
  falsely `column city is missing in the source; without a change log its values are nowhere else…`; following it
  leads into `the change log … exists and this run would not write to it`. Cause: check at load.py:235-243 runs after
  the column loop (180-206); it should come first.
- P4 from the code: `renamed` applied while a FILE table loads is lost: catalog "data" fills the old column empty
  instead of letting it go (load.py:103-106), so the guard at load.py:626-627 (`old in plan["gone"]`) never fires;
  next run `new in had` stops renamed from acting. docs/definition.md says the guard holds.

### Shakedown P20b (Sonnet; scripts in scratchpad/shake/p20b)
- C1 Wrong: a consumer's BEFORE trigger on the mirror that rewrites a value (`new.name := upper(new.name)`): every run
  writes a D and I pair for the row forever, log says `abc`, mirror `ABC`; after a change of key two open versions of
  one row in the history. Not documented. Decide: the smallest that is right (the mirror's rows are the program's: say
  so in docs/target.md + decision 54, with what such a trigger does), unless a cheap stop/detection exists.
- C2 a publication on the mirror stops a change of key with Postgres's bare `cannot delete from table "customers"
  because it does not have a replica identity and publishes deletes`: no publication named, no way out (named for a
  dropped column / changed type, not for a key change).
- C3 a child table (INHERITS) the worker does not own stops every change of columns with `must be owner of table
  child`: no way out (the role must own it or be member of its owner). docs/loading.md.
- C4 minor Wrong: `memo` keeps `was = note` (from an earlier rename) after the source dropped it and it came back as
  another family (old values in `memo__40`): `was` of the new column claims a rename that did not happen to it.

### Bug hunt (Opus; scripts s2.py, s3.py, s7.py, s9.py and harness h.py in scratchpad/hunt) - all CONFIRMED red
- B1 wrong history: an old key column retired in the same run as a key change on a 0.4.1 change log (no comment on
  `_op` yet): load.py:725 `stretches(conn, t) or [{"key": was}]` uses the mirror's names though the log's `b` is now
  `b__N`. Fix idea: `[plan["retired"].get(c, c) for c in was]` as :719-721 do. (s2.py)
- B2 a person's work on the history view is lost without a stop: comment on the view and on its columns,
  `security_barrier`/reloptions, an INSTEAD OF trigger (carry_out drops the view at :686, write_log recreates with the
  grants only). Either carried over like the grants or a stop that names them. Side: a view whose owner a person
  changed fails every run with `permission denied for table p__log`: reason needs the way out. (s3.py)
- B3 `_rowvioli.columns WHERE id = $1` (load.py:247, probably :256-258 too) reads the record across every target name
  a table had: after `target_table` p -> q with another key, a primary key changed by hand on q is taken for the
  definition's change (5 D + 5 I, redundant stretch, nothing recorded). Scope by target schema and table. (s7.py)
- B4 unbounded wait while holding ACCESS EXCLUSIVE on the mirror: a consumer table with a foreign key to the mirror,
  locked by a consumer (`LOCK orders IN EXCLUSIVE MODE`); the run's DELETE/INSERT fire the FK triggers with no lock
  timeout; readers of the mirror blocked meanwhile. Together with S5: one rule for every lock wait after lock(). (s9.py)
- B5 by reading: a first run that creates the schema and then fails leaves the schema (committed before the publish).
  Check; decide (document as intended, or make it part of the publish).

### Shakedown P18b (Sonnet; scripts repro_newline.sh, repro_leaks.sh in scratchpad/shake/p18b)
- X1 Leak (confirms and widens O1): a value in a shown SQLSTATE of other classes too: 42602 `invalid configuration
  parameter name "…"` (set_config), 58P01 `could not open file "…"` (pg_read_file), 0A000 `cross-database references
  are not implemented: …`, a line break inside a quoted value. An allowlist of SQLSTATE codes, not classes.
- X2 a consumer's RAISE that copies the wording of a constraint's message is shown although under its function:
  CONSTRAINT counts only with SQLSTATE class 23 and no function frame.
- X3 the way out printed for a column whose name holds a control character does not work when pasted (written `?`):
  write such a name so that it does, or say that it holds one and how to write it.
- X4 = B2 side: a history view owned by another role: the reason names the view, its owner and the way out.
- X5 a comment on `_op` of the right shape that names a wrong key is trusted silently: stop as for a damaged one.
- X6 check only: `rowvioli run` without a table name and failing tables, against what the documents say.

### Shakedown H2b (Sonnet; scripts in scratchpad/shake/h2b; the rest is ticket 16)
- D1 a key column that changes family in an unpinned Parquet file gets the generic way out `DROP COLUMN "id"`, which
  loses the key column for good: the key's stop (another target_table) comes first.
- D2 a missing ODBC driver library (`Driver={NoSuchDriver}`, SQLSTATE 01000) is withheld: a failure to connect holds
  no row's value and shows.
- D3 with P1: a REST key field that differs in case (`ID` vs `id`): the null key's way out says the field may be
  missing from the answer or named otherwise.

### Shakedown H4b and H1b (Sonnet; scratchpad/shake/h4b, h1b; the connectors, `init` and `SESSION` are ticket 16)
- R1 = I1 a failure before the claim never says its cause: the target restarted at the start gives Postgres's bare
  `FATAL: terminating connection due to administrator command`; a role with `default_transaction_read_only` gives
  `a run process ended with exit code 1 before it claimed anything` four times a second under `work`. The cause is
  said (scrubbed, by the one rule of withheld) by `run` and `work`, and `work` does not repeat it four times a second.
- I2 a role's `statement_timeout` ends a run with the COPY wrapper uncut and no way out: name the setting and the way
  out (`ALTER ROLE … RESET statement_timeout`).
- I3 only USAGE on a pre-created schema gives `permission denied for schema raw_src`: say that the worker's role needs
  CREATE on it.

## Acceptance criteria

- [x] Every item: a test seen red first, or a sentence under Comments why none and what was done instead.
- [x] Documents (`docs/*.md`, decision 54/55, `CHANGELOG.md`) say what changed.
- [x] The whole suite passes.

## Comments

Built on `sc-15` (2026-11-25), test first, one commit per item or per group of items that share their lines.

- O1 and X1 are one rule: an allowlist of SQLSTATE codes, not classes (`SHOWN` in `load.py`, each group with the
  reason its message holds no value). Classes 0A, 54 and 58 and every code of 42 but 42501 are withheld now; ODBC's
  `IM` class went with D2 (a failure of `SQLDriverConnect` shows whatever its code). 55000 (C2's bare message) is
  withheld too; the run names the publication itself. Tested against Postgres for 42601, 42602, 58P01, 0A000;
  SQL Server's 42S02 is withheld by the unit test (the reason still names the table).
- X2: Postgres's own message of a constraint raised inside a consumer's function is withheld now as well (the
  earlier unit test that showed it changed), since its code may copy the words.
- S5 and B4: one rule, `lock_timeout = 50ms` for the rest of the publishing transaction once `lock()` holds; a run
  that meets a lock fails and publishes nothing. The price, in decision 53's note: an `apply` that holds the table's
  row at that moment makes the run fail once instead of waiting; the next run publishes. A short step after a long
  one that a consumer holds up now fails at once (the test of ticket 14 that expected `max_seconds` changed).
- B2: carried over (comment, column comments, options, triggers, rules), not a stop; decision 54 says why. The
  owner of the history view (X4) and of a child table (C3) are stops with the way out: carrying an owner over would
  need rights the worker's role does not have.
- C1, B5: documented, no test (no behaviour changed): `docs/target.md` and decision 54's price.
- X6, checked: `run` ends after a failed table (every `failed()` of the suite runs `run` to its end, exit 1), and a
  failed table waits its pause (`docs/loading.md` "Retry"); no fault.
- R1: no test: a restart of the target in the 0.3 s between `run`'s start and its claim cannot be timed in the suite.
  The run process and the CLI share `lost()` (57P01, 57P02), and I1's path, which carries it, is tested.
- D2: tested in the ODBC container (`tests/odbc/run.sh`), the rule in `withheld()`, since the connectors are ticket
  16's.
- S1: the conftest docstring now says when a test calls a function of the program: six files already did (reason
  lines from drivers not at hand, `work.say`, `definition.read`), so the rule was the untrue part.
- S6 left: the inverse-rename dict built in `check`, `proven`, `fit` and `carry_out` (four contents, merging would
  churn `load.py` for no reader); `connectors/file.py`'s long docstring line (the connectors are ticket 16's).
- S7 left: every test with a Postgres source reads through `cur._results.reader`, so a driver that drops it fails
  the suite at once and loudly; an upper bound in `pyproject.toml` would need a new lock while ticket 16 works on
  the dependencies.
- S2, S3, S4, S6, S8: no behaviour; the suite is the net.
