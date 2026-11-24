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
