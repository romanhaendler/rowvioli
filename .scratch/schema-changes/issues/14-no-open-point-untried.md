# 14: No open point is left: what was never tried

**Blocked by:** 12

**Status:** claimed

**Model:** Opus

The owner on 2026-11-24: no open point of this work at the end, a version without a known fault. Every
review and both shakedown records end in "not checked" or "not covered". This ticket tries each, as a test in
the suite where the seam reaches it, as a measured probe written into `docs/measurements.md` where it does
not, and fixes the program test-first where one goes red. Ticket 13 (built beside this one) changes
`src/rowvioli/load.py` widely: keep changes to the program small and local, and merge its work before
reporting. Spec: `.scratch/schema-changes/spec.md`; decisions 54 and 55.

## What to try

1. **ODBC** (`tests/odbc/run.sh`, `tests/test_odbc.py`; it needs its own image): the whole ODBC suite on
   this branch; `driver_version` of the odbc connector; changes of shape through an ODBC source (a column
   gone and back, a type widened, another family, a key changed, a rename); and no value of a row in a
   reason for what the driver in that image raises (a value that does not convert, a broken type). If the
   image holds one driver only, say which, and for the others (SQL Server, MySQL) say what was done instead:
   the program's rule must not depend on a driver's wording where it can avoid it (any error while reading a
   source gives a reason of ours that names table and, where known, column, and withholds the driver's text
   after its first safe part), or the limit is stated as a decision with its reason.
2. **Excel and JSON files** through every change of shape the CSV tests cover (a header that changes, a pin
   set, changed and taken out, a pattern whose files differ, a field missing).
3. **REST with `renamed`**, with a column taken out of `columns` in the same apply, and with a type changed.
4. **Two `work` processes and a `run` on the same table** while its shape changes: one publishes, the other
   sees the new shape or stops cleanly; nothing half published; the columns table has each change once.
5. **A real `pg_dump` of the target** running while a run wants to change columns, and a dump taken after
   every kind of change restored into an empty database: the history view, the comment on `_op`, the grants
   and `_rowvioli.columns` survive, and a run against the restored target goes on as before.
6. **The first run after an upgrade on a large change log** (ticket 11, item 1: the change log read under
   two keys): how long on 500,000 and on 2,000,000 log rows, against a sensible `max_seconds`; if it can
   outlast it, the reason says so and names the step, as widening does.
7. **The pooler check against another pooler than PgBouncer** (PgCat, Odyssey or Supavisor, whichever has
   a small image): idle and busy, transaction and session mode, how often it misses; `docs/measurements.md`
   section 14.
8. **A consumer's function in PL/Python or PL/Perl raising with a row's value** (ticket 12's review tested
   Postgres's wording without a database): against a Postgres image that has one of them, if a small one
   exists.
9. **`max_seconds` during each long step** of a change (writing a row per row for a dropped column, a
   change of key, the rename proof on a large table): the reason names the step, everything rolls back, the
   next run finishes.
10. **The upgrade with the real 0.4.1** as one test that stays in the suite if it can be had without
    network at test time (the 0.4.1 wheel built from the tag `v0.4.1` in a fixture, cached), covering the
    states the shakedown's U1 built: every stuck state, the grants, old and new program against each
    other's target. If it cannot stay in the suite, a script under `tests/` that the shakedown's U1 host
    runs, and `docs/agents/shakedown/personas.md` says so.
11. Everything else a reviewer or shakedown agent wrote under "not checked" or "not covered" in the
    comments of tickets 01 to 12 and in `.scratch/shakedown/eighth-run.md`: list each here with what was
    done about it. Nothing is left as "not checked" without a sentence saying why it cannot be checked on
    this machine at all.

## Acceptance criteria

- [ ] Each of 1 to 10 has a test, or a measurement on a page, or a sentence here why neither can exist.
- [ ] Every fault found is fixed test-first; the whole suite passes.
- [ ] Nothing in `bench/` is run (`CLAUDE.md`); a test stays small enough for the suite, a larger probe is
      run once by hand and its numbers written down.

## Comments

Implementation on `sc-14` (2026-11-24), one commit per item, in the order 1, 10, 4, 5, 2, 3, 9, 6, 7, 8, 11.

- 1, **a fault, fixed**: through psqlODBC a value that does not convert (`invalid input syntax for type integer:
  "…";`, the driver appends `;`) and a consumer's `RAISE` in a source view (`bad row …`) reached the reason. arrow-odbc
  writes the SQLSTATE every ODBC driver gives (`State: 22P02, Native error: 1, Message: …`), so the rule is the
  SQLSTATE, not the words: class `22` (data exception) is withheld with the state named, `P0001`/`P0004` go the way of
  a consumer's function. The image holds psqlODBC only; SQL Server's conversion error is `22018` and MySQL's quotes
  are not read, so the rule holds for them by the ODBC standard, untried here: no SQL Server or MySQL driver or server
  is on this machine (licences, decision on vendor drivers). The whole ODBC suite passes in
  `tests/odbc/run.sh` (13 passed, 1 skipped as before), `driver_version` asserted; changes of shape through ODBC: a column gone and back, widened,
  another family, a rename proven, another key, the log replaying. Decision 54 item 8, `open-points.md`, changelog.
- 10: `tests/test_upgrade.py`, in the suite, offline: the source of the tag `v0.4.1` (`git archive`), run with the
  suite's Python and libraries, builds the stuck states (column gone, gone with a consumer's view, another family,
  a numeric that outgrew its type, primary key changed by hand, key changed in the definition, a person's column,
  without key, without log); `init` as a role without rights changes nothing; `init` gives the same catalogue as a new
  target; old and new refuse each other's target; every table loads or stops with its way out, which leads out; the
  history before the upgrade holds. The key changed in the definition stops once asking for the comment on `_op`
  (0.4.1 hashed the whole definition and the log had first rows only), as documented. The grants by a worker's role
  of least rights stay with `tests/test_init.py` (a simulated version 3) and the U1 host (`personas.md` says so).
- 4: two `work` and two `run` on one table through four changes: each recorded once, in order, no failed run.
  The table lock serialises them, so no run ever sees a shape another is publishing.
- 5: `tests/test_dump.py`: a run that changes columns while `pg_dump` holds its share lock gives up after 10 s, rows
  alone load meanwhile, the next run makes the change; a dump after a column gone, widened, retyped, renamed and a
  key changed restores (`pg_restore`) with the history view, its grant, the comment on `_op` and the columns table
  equal, and a run against the restored target goes on. `docs/operation.md` says it.
- 2, 3: no red. REST has no two types of one family (`int8`, `float8`, ...), so "a type changed" with `renamed` is
  one of another family, which stops with `take m out of renamed`; its way out leads out.
- 9, **a fault, fixed**: a run ended at `max_seconds` while it wrote the log rows of a gone column, replaced a mirror
  under another key or ran the proof of a rename said only `ended after max_seconds = 2`, and the next run would end
  the same. The run now tells the worker each such step as it told a widening (`{"long": …}`), and the reason names
  it with the advice to raise `max_seconds` once. Everything rolls back; the next run with the raised value finishes.
- 6: measurement 16: 0.56 s per read at 500,000 log rows, 1.3 s at 2,000,000; outlasting 3600 s needs billions. The
  read is now a named step too (tested with a consumer holding the log).
- 7: not tried. PgCat's official image is 248 MB, Supavisor's over 360 MB compressed, Odyssey has no official image
  nor binary; building Odyssey from source in a throwaway container was refused by this machine's permission rules.
  Measurement 14 says so; whoever runs it needs a pooler image or the permission to build one.
- 8: tried against `postgres:16-alpine` with `perl` and `python3` added (the image has the languages' libraries
  only): PL/Perl and PL/Python, in a trigger on the target and in a source view, are withheld with the function named
  (SQLSTATE `38000` for PL/Perl, `XX000` for PL/Python). The four tests skip in the suite and say how to run them.

Item 11, every "not checked", "not tested" or "not covered" of tickets 01 to 12 and of `eighth-run.md`:

- 02: a person's column in the mirror: tested since (`test_a_column_a_person_added_to_the_mirror_is_never_dropped…`).
  A type widened by hand other than numeric: tested since (`test_a_type_of_any_family_widened_by_hand…`).
- 03: A12 with values that do not fit: tested since ticket 04 (`test_A12_…widens_the_log_column`). Story 10's "name
  that is taken": tested since ticket 11 (`test_a_retired_name_the_source_takes…`).
- 04: B2, B3, B5, B7, F5 never seen red: seen red now by a mutation that never widens (7 tests red). B4 survives a
  mutation of the type map, since no code path alters a type for a narrowing; the test guards the outcome. F4 for
  REST: tested since (`test_F4_B11_…by_definition` in `test_rest.py`).
- 05: C7: tested since ticket 04 (`test_C7_…`). "The reason names the source's primary key" and C11: not asked by
  any decision, nothing to check.
- 06: the "not assumed" cases, A27, A31 and the stated renames never seen red: seen red now by mutations (no proof:
  3 red; a proof across families: A27 red). A28 is the documented limit and is tested as such.
- 07: the documents against ticket 09: checked, `loading.md` quotes the reason the code gives word for word.
- 08: the ODBC `driver_version`: run in `tests/odbc/run.sh` (item 1).
- 09: an ODBC driver's message: fixed by item 1. A connector of one's own whose message holds a value: a stated
  limit (decision 54 item 8): no rule tells a value from a name in text a stranger's code writes.
- 10: D6, G6, H3 never seen red: seen red now by mutations (the history view dropped with `CASCADE`, a gone column
  dropped with `ONLY`, the record written after a `COMMIT`). Item 10's Arrow message: tested since ticket 12
  (`1.5e400` in `test_run_mistakes.py`). Item 4 for REST: tested now (`test_A20_a_rest_column_name…`).
- 11: a 0.4.1 change log under two keys: tested now (`test_a_change_log_from_before_the_upgrade_that_fits_neither…`):
  it stops with both statements. A table without a change log whose definition changed: taken as a key changed by
  the definition by decision; only `by` can differ, `open-points.md` says so. The view's owner given away by hand:
  the run creates the view as its own role, which `target.md` says; a grant passed on with its grant option: ticket 13
  item 4 decides it. A CSV header name with a line break in a reason: tested since ticket 12
  (`test_a_name_with_a_line_break_in_a_reason_that_crosses_arrows_stream…`).
- 12: PL/Python and PL/Perl: item 8. A foreign key and a view on the key in the same run as a view on a column:
  tested now (`test_a_foreign_key_and_a_view_on_the_key_are_named…`), all three named, one round clears them. Another
  pooler: item 7. A history view built before the change reading a child table of the change log until a run builds
  it anew: 0.4.1 never read a change log with `ONLY`; the view is rebuilt by the first run that changes columns, and a
  consumer's child table of a change log is a case no version created; stated in ticket 12, nothing more to try.
- `eighth-run.md`, "not covered by any": ODBC (item 1), Excel and JSON (item 2), a real `pg_dump` (item 5), two `work`
  on one table (item 4), a superuser `init` (every test of the suite runs `init` as the superuser `postgres`),
  `renamed` applied during a load: tested now (`test_renamed_applied_while_a_run_loads…`): the loading run keeps the
  definition of its claim, so the column goes and comes with its values in the log, and the next run leaves it;
  `definition.md` says to state it before the source renames. A real 0.4.1 fleet over days: cannot be had in a
  session; item 10 is the same states in minutes. "Not run: P1, P3, P4, P16, P22 and the reviewers": personas are a
  shakedown wave the owner starts before a release (`docs/agents/shakedown/README.md`), not part of this ticket.
