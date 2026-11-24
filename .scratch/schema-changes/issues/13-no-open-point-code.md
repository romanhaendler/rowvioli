# 13: No open point is left: the program

**Blocked by:** 12

**Status:** ready-for-agent

**Model:** Opus

The owner on 2026-11-24: at the end no open point of this work is to be seen, and the version is to be one
without a known fault, to the highest standard. This ticket closes in the program what the tickets, reviews
and `docs/open-points.md` still list from this work. Ticket 14 (built beside this one) closes what was never
tried; it adds tests and touches the program only where a test goes red. Spec:
`.scratch/schema-changes/spec.md`; decisions 54 and 55.

## What to build

1. **A retired column is known by what the change log says, not by its name.** Today `<name>__<digits>`
   beside a log column `<name>` counts as retired, so a real source column `x__2024` that goes and comes
   back stops. The retirement is written where the keys are written (decision 9: with the change log, and
   nothing in `_rowvioli` is needed to read it): a comment on the retired log column, or an entry in the
   comment on `_op`, whichever keeps one mechanism. Nothing is decided by the pattern any more; the stop
   "a name that is taken" stays for a real clash of names. The version is not released, so nothing is
   migrated.
2. **A connector says that it has no catalog.** `t["type"] in ("file", "rest")` in four places becomes an
   optional entry of the connector contract, as `driver_version` and `OWN_TYPE` are; the shipped `file` and
   `rest` say it, a connector of one's own may, and one that says nothing has the rules of a database
   source as today. `docs/connector-guide.md`.
3. **A field named under `columns` that a file lacks is empty**, as for REST (ticket 08, item 4: named in
   the definition and missing from the data is empty and never goes), instead of DuckDB's
   `Binder Error … not found in FROM clause`. For every reader of the file connector, one file and a
   pattern.
4. **A grant on a history view comes back as it was given**: by the grantor that gave it, where Postgres
   lets the run's role do that (`GRANTED BY`, or acting as a role it is a member of); where it does not,
   the run stops rather than change who a grant comes from? No: find out what Postgres 14 to 17 allow,
   take the way that loses and widens nothing, and where nothing allows it keep ticket 11's behaviour and
   say exactly when (decision 54), tested.
5. **A reason names a dependent object with its schema**, always, as the other reasons name tables
   (`pg_describe_object` leaves out what is on the search path); and **an object that was in use during a
   refused change is named**, if the catalogue can say it without taking a lock; if not, a sentence here why.
6. **`_rowvioli.columns` is read by `id` on every run**: an index in the version 4 step, as
   `columns__log` has.
7. **What the review of the whole left in `load.py`** (ticket 10, item 11, and the standards review's
   judgement calls): the `moved` mapping built twice with different contents under one name, the test
   whether `renamed` applies written twice, two stops for one rule in `check()`, `staged`/`mirror`/`log`
   columns re-dicted in four functions, `publish()` with nine parameters, `log` meaning a list here and a
   bool there, `by` decided in three passes of `record_columns`. Change what makes the code easier to read
   and harder to get wrong, with no change of behaviour and the whole suite as the net; where two places
   must agree, make them one. Not a rewrite: each step small enough to review by its diff.
8. **A message from a consumer's function in C or in a language that names no frame** (ticket 12's review):
   decide by test what such an error looks like to the driver; if the target's errors during publishing can
   be told apart as "Postgres's own with a known shape" or "anything else", anything else is withheld as a
   consumer's function's message is. If that would hide reasons an operator needs (disk full, a lost
   connection, a missing right), keep those shown: they hold no value of a row.

## Acceptance criteria

- [ ] 1 to 6 and 8: a test each, seen red first, at the existing seam; the replay invariant where columns change.
- [ ] 7: no test changes its assertions.
- [ ] The whole suite passes, with the pgbouncer image present too.
- [ ] `docs/` say what is true after this; ticket 14 or 15 rewrites `docs/open-points.md`, leave that page's structure alone but correct the entries this ticket makes false.

## Comments
