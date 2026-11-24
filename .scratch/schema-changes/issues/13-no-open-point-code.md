# 13: No open point is left: the program

**Blocked by:** 12

**Status:** claimed

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

Implementation on `sc-13` (2026-11-24), one commit per item, item 7 in six; what is not done or not tested, each
with why and what closing it would take:

- 1: the retirement is a comment on the retired log column, `{"retired": "<name>"}`, not an entry in the comment on
  `_op`: a comment follows its column when a person renames it (the way out of A19) or drops it, where an entry in
  `_op`'s comment would keep naming a column that is gone or is now the source's. One mechanism all the same: the
  change log's comments on its columns say what it knows of itself, read by one function (`comments`), and a lost
  one stops with the text to put back, the keys' from the columns log, a retired column's from its note in the
  columns table. A change log from this branch's earlier commits has retired columns without the comment; they count
  as ordinary log columns (nothing is released, nothing migrated). A rename of a retired column's base leaves the
  comment naming the old base, which is what its values were.
- 2: the entry is `catalog`, with two values, not a flag: REST and file differ in whether a column the data lack goes
  (`"definition"`: it was taken out of `columns`) or is empty (`"data"`), and one flag cannot say both without the
  rule naming the connector again. Tested for a connector of one's own with `"data"` and without the entry;
  `"definition"` is tested through the shipped `rest` only.
- 4: Postgres 14, 15, 16 and 17 all refuse `GRANTED BY` any role but the current one (`grantor must be current
  user`, tried in containers of each). `SET ROLE` to the grantor works on all four where the session's role is a
  superuser or a member that may set it (16 and 17: `WITH SET TRUE`, the default). Tested as a superuser, a member and
  a worker's role alone (the fallback, the grant by the worker's role). A grant whose grantor no longer holds the
  grant option (Postgres keeps such a grant when the grantor's table grant is revoked but a column grant remains)
  comes back as no grant, with Postgres's warning; not tested.
- 5: the object in use is named from the catalogue for a drop of a column, of the history view and of a primary key
  (through its index, for a foreign key); tested for a column. A view that reads no column of the history view
  (`select count(*)`) depends on the view as a whole and is named too; a drop for which the catalogue finds nothing
  keeps the old sentence.
- 8: told by SQLSTATE class, not by words: while publishing, classes 08, 0A, 25, 2B, 40, 42, 53, 54, 55, 57, 58 and a
  constraint's message are shown, everything else withheld. What stays: a C function that raises in one of the shown
  classes, and a value where Postgres's message of those classes puts a name (`relation "Anna" does not exist` of a
  cast to `regclass` in a check constraint); an error before publishing (a policy on the mirror during the diff).
  Closing it would take telling a name from a value in Postgres's messages, which nothing does.
- 7, done: one `moved` (the plan's), the renames' own mapping named `renamed_to`; whether a stated rename acts tested
  once, in `load`; the two stops of "a run never ends a change log" one stop (it now comes before the key is looked
  at: a table that breaks it and has a changed key that nothing in the target explains is told about the change log
  first, where it was told about the key; no test has both); `log` a setting and `log_columns` columns throughout;
  `by` decided in one pass after the rows are built (the reader's versions are now read whenever rows are recorded).
  Decided not to do, in the review: the columns as dicts from the start (four functions call `dict()` on the lists): it would change every
  loop over columns in `load.py` (`.items()` in about ten places, `staged + [...]` in `diff`), one large diff the
  night before the release for no change a reader meets; `publish()` keeps its nine parameters, which are the
  pipeline's facts in its order, and bundling them would hide which step reads which. Both change no behaviour and
  no reader meets them; a large mechanical diff of `load.py` the night before 0.5.0 is a risk with nothing to gain, so
  they stay as they are by decision, not as an open point.

Review (2026-11-24), fixed on `sc-13` test first: a change Postgres refuses ran under an empty search path, so a
consumer's event trigger or check constraint whose function finds its table on the path failed every run that changed
columns (item 5: only the catalogue's naming runs under the empty path now); a grant passed on whose grantee lost USAGE
on the schema failed every run that built the history view anew (item 4: the worker's role gives it, as where it may
not act as the grantee; tested on Postgres 14, 16 and 17); a `catalog` other than `"data"` or `"definition"` was taken
half for each (item 2: refused with the value; `"definition"` tested for a connector of one's own); while publishing
an object that does not exist is withheld too (`relation "anna2" does not exist` of `::regclass`), and Postgres's own
messages of a constraint a widening checks again are shown (item 8); an old key column retired in the run the key
changes failed the run (item 1); the merged stop of item 7 is tested; a key column named under `columns` that no file
has stops as null (item 3). A misspelt name under `columns` is an empty column, as in REST: the old Binder Error caught
it, but a pin set before a file brings its column must not stop the table, and the empty column shows the mistake.
