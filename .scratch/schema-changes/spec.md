# Schema changes: the mirror follows the source, the change log keeps what was

Status: resolved

The design and its reasons are in `strategy.md`, every single case in `cases.md`, the Postgres behaviour it builds on in `facts.sql`, and a prototype of the mechanics in `experiments/09_schema_changes.sql`. Where they and this spec differ, this spec holds.

## Problem Statement

A source table changes its shape: a column is dropped, a type changes, a column is renamed, the key becomes another. Today rowvioli adds a new column by itself and stops for everything else (decision 17). The table then fails with every run, its mirror ages, and a person runs statements from `docs/loading.md` by hand on the target. Those statements leave no record: nobody can say later when a column went, what its type was before, or who altered the mirror. Following the recipe for a dropped column deletes its values from the change log and so from the history. A changed key costs the whole history, or three objects renamed by hand.

An operator with two hundred tables gets these stops at night, for changes that needed no decision. An auditor asking "which columns did this table have on 1 March, and what happened to the values of the column that is gone" gets no answer from the target.

## Solution

The mirror follows the source wherever a change log keeps what was. A column the source no longer has leaves the mirror and stays in the change log with every value it had. A change of columns is written as a change of rows, so the change log still replays to the mirror and the history ends the version that had the value. The columns of every mirror are themselves kept in a table with its own change log and history, so "what did the table look like then" is the same query as for rows.

A run stops only where somebody built on what would change: a consumer's view, foreign key or other object that Postgres knows to depend on it. Postgres refuses the change, nothing is published, and the reason names the object. Who wants to be asked before a column changes builds a view on it.

```
The source drops city and adds region. One run, one transaction.

raw_erp.customers        id, name, city   →   id, name, region
raw_erp.customers__log   id, name, city   →   id, name, city, region     one U per customer
_rowvioli.columns__log   U  raw_erp.customers  city    mirror = false  by = source  run 812
                         I  raw_erp.customers  region  mirror = true   by = source  run 812
```

## User Stories

### Columns

1. As an operator, I want a column the source dropped to leave the mirror by itself, so that the table keeps loading without me.
2. As a consumer of the history, I want the values of a dropped column to stay in the change log and the history view, so that nothing I could read yesterday is gone today.
3. As a consumer of the history, I want the version of a row that had a value in a dropped column to end at the moment the column went, so that the history does not show a value the mirror no longer has.
4. As a consumer, I want the change log to replay to the mirror after a column went, so that the log stays the complete record it is today.
5. As an operator, I want the rows of a large mirror not rewritten when a column is dropped, so that a drop costs log rows and not a rewrite of the mirror.
6. As an operator, I want a column that comes back with the same type to continue its old column in the change log, so that its history has a gap and not a second column.
7. As an operator, I want a column that comes back in another family of types to begin a new column while the old values stay under `<name>__<run>`, so that old and new values are never mixed.
8. As a person who added a column of my own to a mirror, I want a run never to drop it, so that my data is not destroyed because the source does not have it.
9. As an operator of a table without a change log, I want a dropped column to keep stopping the run, so that values that exist nowhere else are not removed without a person.
10. As an operator, I want a run that would exhaust Postgres's 1600 columns, or needs a name that is taken or too long, to fail with a reason that says what to do, so that I am not left with Postgres's bare message.

### Types

11. As an operator, I want a mirror to keep its type while every value fits, whatever wider type the source declares, so that a view on the mirror does not stop a table that loads fine.
12. As an operator, I want a type widened in mirror and change log at the moment a value needs it, so that `integer` to `bigint` or more digits in a `numeric` never need me.
13. As an operator, I want a source that narrows a type to change nothing in the target, so that old values always fit.
14. As an operator, I want a type of another family (`text` to `integer`, `timestamp` to `timestamptz`) handled as a column that goes and comes, so that there is one rule and no reload.
15. As an operator of a file or REST source, I want a guessed type that flips to another family to stop the run with the hint to pin it under `columns`, so that a single odd value does not retire a column.
16. As an operator, I want a run ended after `max_seconds` while it widened a column to say so and name the column, so that I know to raise `max_seconds` once.

### Keys

17. As an operator, I want to name a key for a table that had none and have the next run add the primary key and begin the change log, so that I do not drop the mirror first.
18. As an operator, I want to change a table's key in the definition and keep its history, so that a changed key no longer costs the change log.
19. As a consumer of the history, I want the table as it was at a moment to be right before and after a change of key, so that I can query across it.
20. As an operator, I want the same key columns in another order not to be another key, so that reordering a list does not stop a table.
21. As an operator, I want a key column widened like any other column, so that an id outgrowing `integer` does not stop the table.
22. As an operator, I want a key that no longer identifies a row, a key taken away while a change log exists, and a key column in another family to stop the run with a reason, so that the program never guesses what identifies a row.
23. As a consumer with a foreign key to a mirror, I want a change of its key to stop and name my foreign key, so that I am asked.
24. As an operator, I want a primary key that somebody changed by hand put back to the definition's, so that the mirror and the change log agree again.

### Renames

25. As an operator, I want a renamed column recognised when the data prove it, so that its history continues under the new name and no row is written.
26. As a consumer with a view on a renamed column, I want my view to keep working under its own column name, so that a rename in the source does not break me.
27. As a consumer, I want a rename never assumed for a flag, a small table or two candidates, so that my view is not pointed at another column without a word.
28. As an operator, I want to state a rename in the definition where the data cannot prove it, optionally, so that a renamed flag or a renamed key column is a rename and not a drop and an add.
29. As an operator, I want a stated rename to do nothing while the old column is still delivered, so that I can leave it in the definition.

### Sources without a catalog

30. As an operator of a file or REST source, I want a column missing from one file, one page or one run to be empty and not gone, so that an API that leaves out empty fields does not change my table.

### The record

31. As an auditor, I want to ask which columns and types a mirror had at a moment, so that I can read old rows correctly.
32. As an auditor, I want every change of a column recorded with the run, the moment and what caused it (source, definition, reader, hand), so that I can tell a change of the source from a change of ours.
33. As an auditor, I want the moment of a column's change to be the moment of the rows loaded with it, so that I can say which rows were loaded under which columns.
34. As an auditor, I want the type the source delivered kept beside the type in the target, so that a mirror that is wider than its source is explained.
35. As an auditor, I want a change made by hand on a mirror or its change log recorded by the next run that publishes, so that the record has no silent holes.
36. As an auditor, I want to know which indexes, checks and column grants went with a dropped column, so that what Postgres removes without a word is on record.
37. As an auditor, I want to read all this with the right on one view, so that I need no rights on the bookkeeping.
38. As an auditor, I want a change that came with another version of the program or the driver marked as such, with both versions, so that I do not take it for a change of the source.
39. As an operator, I want a mirror renamed by hand to appear in the record under its new name with the old name closed, so that the record follows what is there.

### Consumers and operation

40. As a consumer, I want a run to stop and name my object when a column, type or key I depend on would change, so that I change my view before the data change under it.
41. As a consumer with a view on a history view, I want to know that it stops changes to any column of that view, so that I can decide whether to build one.
42. As a consumer, I want to be notified at the moment a change of columns is committed, and never for one that was rolled back, so that I can react without polling.
43. As a consumer joining a history view with its mirror, I want a run never to wait for a lock while holding one, so that Postgres does not end my query to break a deadlock.
44. As an operator, I want all changes of one run to be published together with its rows or not at all, so that a reader never sees new columns with old rows.
45. As an operator, I want a table that is stuck today on `is missing in the source` or `has changed its type` to resolve itself with the first run of the new version, so that the upgrade clears my list.
46. As an operator, I want `rowvioli init` to bring an existing target to the new version of the bookkeeping, and old workers to refuse it, so that no worker writes without the record.
47. As an operator, I want every reason of a stop to say the way out, so that I do not need the documentation at night.
48. As a reader of the documentation, I want the recipes for what a run now does itself removed, and the ones that remain named as such, so that the page says what is true.

## Implementation Decisions

### The rules

1. **Where a run acts by itself.** On a table with a key and a change log, by all rules below. On a table without a change log only additions, changes of key and stated renames are automatic; a column that is gone or of another family stops the run with today's reasons.
2. **A column comes.** If the change log holds that name in another family, that log column is renamed to `<name>__<run>`. Then mirror and change log get the column where they lack it. The diff writes a `U` for every row with a value in it, as today.
3. **A column goes.** If the change log has it: dropped from the mirror, kept in the change log, and the change log gets a `U` for every row that had a value. Those rows are not applied to the mirror. If the change log does not have it, the run fails with `column x of the mirror is not in the change log, so it is not known to be from the source`. For a connector without a catalog (file, REST) a column missing from the data is an empty column and never goes.
4. **Families.** The exact numbers (`smallint`, `integer`, `bigint`, `numeric`); the floats (`real`, `double precision`); `date` and `timestamp`. Every other type is a family of its own, including `text` and `timestamptz`. The list is fixed in the code.
5. **A type of the same family.** The target keeps its type while every staged value fits. One test for all families: cast to the target's type and back gives the same value, and a cast that raises does not fit. When a value does not fit, mirror and change log are altered to the type that holds both: the larger integer; for `numeric` the larger number of digits before and after the point, an integer counting as 5, 10 or 19 digits before and none after, and unconstrained `numeric` beyond what Postgres can declare; `timestamp`; `double precision`. This replaces the handling of `numeric` alone from decision 49.
6. **A type of another family** is a column that goes and comes (3 and 2) in one run. It stops instead for a connector without a catalog (reason: pin the type under `columns`) and for a key column.
7. **A key.** Compared with the mirror's primary key as a set, after renames. Another key or a first key: the mirror is replaced as a whole, as for a table without a key; the primary key is dropped; `NOT NULL` is dropped from old key columns that are not in the new key; the new primary key is added. A change log that exists gets a `D` for every old row and an `I` for every new row with the moment of the run; one that does not exist begins with every row, as today. A key taken away stops with a change log, as today, and drops the primary key without one. A primary key that differs from an unchanged definition is put back.
8. **The history view after a change of key** has one branch per key, joined with `UNION ALL`, each over its own stretch of the change log and partitioned by its own key. A stretch is cut by `_loaded_at` and `_op`: up to the moment of the change and its `D` rows, from its `I` rows on. Not by `_run`. From the prototype, for a change at moment `T` from key `(id)` to `(id, tenant)`:

   ```sql
   SELECT … lead(_loaded_at) OVER (PARTITION BY id ORDER BY _loaded_at) …
     FROM log WHERE _loaded_at < T OR (_loaded_at = T AND _op = 'D')
   UNION ALL
   SELECT … lead(_loaded_at) OVER (PARTITION BY id, tenant ORDER BY _loaded_at) …
     FROM log WHERE _loaded_at > T OR (_loaded_at = T AND _op = 'I')
   ```

9. **The keys of a change log are kept with it**, as the comment on its column `_op`: the list of keys and the moments they changed. The history view is built from that comment and from nothing in `_rowvioli` (decision 40). A change log without the comment has had one key. A run that renames or retires a log column rewrites the comment in the same transaction. If the comment is missing or unreadable while the columns table records a change of key for the table, the run fails and gives the text to put back.
10. **A rename.** One column gone and one come in the same run, same family, is a rename in mirror and change log, with no row written, when the data prove it or the definition states it. The proof is one query over the mirror's old column and the staged new one, joined by the key, over the rows whose other columns are unchanged: every such row equal, at least 20 such rows, at least 5 distinct values, exactly one candidate for the gone column, and the new name not in the change log. Nothing is proven for a connector without a catalog or a table without a key. The statement is a new optional table setting `renamed = { new = "old" }`; it acts when `old` is gone and `new` has come, on any table, and does nothing otherwise. A stated rename whose two columns are of different families fails the run.
11. **A changed reader does not stop.** `_rowvioli.runs` records the version of the program and of the driver. A connector may say its driver's version; that is an optional addition to the connector contract, and a connector that says nothing has none. When a run changes columns and its versions differ from those of the table's last successful run, or that run has none, the changes are recorded with `by = reader` and both versions in the note.

### The flow of a run

12. **A plan before the diff.** After staging, the check compares staging table, mirror, change log, key and `renamed` and produces what the run will do to the columns: renames, columns that go, log columns to retire, types to widen, the key. Every stop that follows from a rule happens here, before anything is written. Stops that only Postgres can find (a dependent object) happen in publishing and roll everything back.
13. **The diff follows the plan.** It runs over the columns of mirror and staging table together, empty where a side lacks one; a renamed column is compared with its new name; a retired column is read under its retired name and never compared with its successor.
14. **Publishing**, one transaction as today, in this order: lock mirror, change log and history view in one statement with `NOWAIT`, retried for up to ten seconds, whenever the plan holds anything but added columns; drop the history view in the same case; carry out the plan; apply the diff to the mirror, without the rows that differ only in a column that went, and write all of it to the change log; create the history view; write the columns table; `pg_notify`; the check of the target name (decision 53) last.
15. **Reasons.** A refusal by Postgres is reported with its detail, which names the dependent object, after a sentence of ours that says which column or key would have changed. Widening is a step of its own in the reason of a run ended after `max_seconds`.
16. **Notification.** Channel `rowvioli_schema`, once per run that changed columns or key. The payload is small and fixed: target schema, target table and run. A listener reads the changes from the columns table.

### The columns table

17. **`_rowvioli.columns`**: one row per column of a mirror or of its change log, keyed by target schema, target table and column. Fields: `type` (in the target), `source_type` (as the connector delivered it), `key` (position in the key or empty), `mirror` (whether the mirror has the column), `was` (the name before a rename or a retirement), `by` (`source`, `definition`, `reader`, `hand`, `found`), `note`, and `id` (the table's id in `_rowvioli.tables`, not part of the key).
18. **`_rowvioli.columns__log` and `_rowvioli.columns__history`** are to the columns table what a change log and a history view are to a mirror, with `_op`, `_run`, `_loaded_at`, `_valid_from`, `_valid_to`, and `_loaded_at` equal to that of the rows published in the same transaction. They are written in the publishing transaction only, for every table, with or without a key.
19. **What a row looks like.** A column that left the mirror: `U` to `mirror = false`. A rename: `D` of the old row and `I` of the new with `was`. A retired column: an `I` of `<name>__<run>` with `was` and `mirror = false`, beside the row of the name, whose type changes. A type pinned or cast in the definition: `by = definition`.
20. **By hand.** Before a run acts it compares the columns table with the catalogue for its mirror and change log. Differences are recorded with `by = hand` at the moment of this run. A widened type made by hand in the mirror is followed in the change log.
21. **First fill and renamed targets.** A table without rows in the columns table gets one per column with `by = found`. A run that finds rows carrying its table's `id` under a name that is no table any more closes them (`D`, `by = hand`) and enters its columns under its name with `by = found`.
22. **The note** of a dropped column lists the indexes, check constraints and column grants that Postgres drops with it, read from the catalogue before the drop. The note of a proven rename holds the three numbers of the proof.
23. **Rights.** Workers write the three objects. Whoever may read `columns__history` needs nothing else in `_rowvioli`. The grants in `docs/operation.md` are extended.

### The bookkeeping

24. **Version 4 of `_rowvioli`** adds the columns table with its log and view and the two version columns of `runs`. `rowvioli init` on a target of version 3 brings it to 4 and changes nothing else; on a target of version 4 it does what it does today. This is the first migration; it is written as a list of steps so that a later one is one more step. Workers of the old program refuse the new version, as they do today.

### Documents

25. **Glossary.** "Mirror" and "Change log" say what follows the source and what is kept; "replaying it from its first row" becomes "from the last change of key". New terms: columns table, family (of types), retired column.
26. **A new decision** records all of this and marks decisions 17, 31 (a changed key stops), 40 (replay) and 49 (the numeric exception) as changed, in the manner of the existing "Changed by decision …" notes.
27. **`docs/loading.md`**: the table of checks and "What a person does by hand" are rewritten: the recipes for a dropped column, more digits and a changed key go for tables with a change log, stay for tables without one, and each remaining stop has its way out. **`docs/target.md`**: the columns table, the notification, what a consumer's view means, the note that a prepared `SELECT *` fails once after a new column. **`docs/definition.md`**: `renamed`. **`docs/connector-guide.md`**: the driver's version. **`docs/operation.md`**: grants, the upgrade with `init`, and that all workers of a target run the same drivers. **`docs/open-points.md`**: the two open points on missing columns of REST pages and file patterns are closed; new ones from "Further Notes".

### Stages and who implements

The owner's rule (`CLAUDE.md`): the smallest model that fits; Opus reviews at the end. To be checked again per ticket.

| | Work | Model |
|---|---|---|
| 0 | Tests of the program as it is for the five untried cases (`cases.md` A20, A22, B14, B16, F8). Version 4 of the bookkeeping and the migration in `init`. Program and driver version in `runs` and in the connector contract | Sonnet. Specified and mechanical |
| 1 | The columns table with first fill, changes by hand and renamed targets; `pg_notify`. No change of what a run does to a target table | Sonnet |
| 2 | The plan and the diff by it; a column goes and comes back; missing columns of file and REST sources | Opus. It changes the flow of a run |
| 3 | Types: the fit test for every family, widening, another family | Opus |
| 4 | Keys: order, first key, changed key, the history view by stretches, the comment on `_op` | Opus |
| 5 | Rename: proof and `renamed` | Opus |
| 6 | Documents and the new decision | Sonnet |
| | Review of each stage | Opus |

Each stage leaves the program releasable. Stages 2 to 5 do not need the columns table to work; it records what they do.

## Testing Decisions

- **The existing seam, nothing new.** Tests start the commands as real processes against real PostgreSQL in Docker and look only at what a user sees: the target tables, the views in `_rowvioli`, the reason in `status`, stdout and stderr. No test imports a module of the program. A change of the source is an `ALTER TABLE` on the source database of the harness; a consumer is a view, an index or a foreign key created on the target; an auditor is a query on `columns__history`.
- **A good test** states one line of `cases.md` or one user story and would pass if the plan, the diff or the publishing were written anew. It asserts what a consumer can read: the columns of the mirror, the rows of the history at a moment, the rows of `columns__log`, the reason. It does not assert the statements a run issues.
- **The invariant is asserted in every test that changes columns or key:** the change log replayed gives the mirror. One helper in the tests does the replay, as the prototype's does.
- **`cases.md` is the list.** Every line with a proposed behaviour that differs from today gets a test named after its number, or a sentence in the ticket why not.
- **Another reader** is played by the test connector in `tests/connector`, which reports a driver version given to it; no second driver is installed.
- **The notification** is tested with a second connection that listens, for a run that commits and for one that a consumer's view makes fail.

What is tested, by stage (prior art in brackets):

0. The five untried cases, as they behave today (`tests/test_run.py`, `tests/test_file.py`). `init` on a version 3 target; an old worker against version 4 (`tests/test_init.py`).
1. First fill with `found`; a new column gives an `I`; a column added, dropped and widened by hand gives `hand`; a mirror renamed by hand; `columns__history` answers "columns at a moment" (`tests/test_history.py`). Notification on commit only.
2. A5 to A16 and A19, A23 of `cases.md`: goes, comes back in each of the three ways, is not from the source, is read by a view, has an index and a grant; without a change log; F1, F6 for file and REST (`tests/test_checks.py`, `tests/test_rest.py`). The mirror's untouched rows keep their `ctid` or are otherwise shown not rewritten when a column goes.
3. B1 to B8, B11, B13, B19; a view on the mirror while values fit, and when one does not (`tests/test_numeric.py`); F4, F5.
4. C1 to C15 except C11; the history at moments before and after the change, with a row whose new key column changed under the old key; the three objects renamed by hand after a change of key; the comment removed.
5. A24 to A28, A31; a flag, a small table, two candidates are not proven; `renamed` for a key column, on a table without a log, left in place while the old column exists.
6. `tests/test_guide.py` and the like keep the documents' examples true.

Not tested: the time a large change log is locked while a type is widened or a column's rows are written. That is a measurement in `bench/`, run when the owner asks (`CLAUDE.md`). Disk space: the harness's rule stands, containers and volumes are removed after the session.

## Out of Scope

- A switch for the old behaviour, policy modes, contract files (decided by the owner).
- A stop when the reader changed, and a command that lifts one (decided by the owner).
- `COMMENT ON COLUMN` with the source's type (until somebody asks).
- Tamper evidence for the columns table's log.
- Leaving a column out of a database source; a source column named `_op` still stops its table.
- Finding new tables in a source; a dry run.
- Recording who ran `apply`; `runs.definition` already holds the hash of the definition a run loaded under.
- Ending a change log by the program: `log = false` and a key taken away still stop while a change log exists.
- The source's declared lengths, constraints, defaults and comments. A mirror has none of them, and their changes leave no trace.

## Further Notes

- **Prices the owner accepted with the design**: a dropped column and a type of another family cost one change-log row per row; a changed key two, and a rewrite of the mirror; widening can rewrite mirror and change log under an exclusive lock; a view on a history view stops changes to any column of it; an upgrade that delivers a type in another family writes a row per row on every affected table once.
- **Known limits, to go into `docs/open-points.md`**: a declared length of the source is not recorded (Arrow carries none); a change by hand is dated when it was noticed, and not at all while its table fails; a person who changes primary key and definition by hand and keeps the change log leaves a seam nobody recorded; a column dropped from the change log by hand and then dropped in the source stops with "not in the change log"; two columns that swap names, or a name reused in the run its column was renamed, are not seen by any loader.
- **The numbers of the proof** (20 rows, 5 values) are a proposal, strict on purpose because a false proof points a consumer's view at another column. They are constants in one place.
- **What the prototype did not cover**: the comment on `_op`, dependent objects of consumers (those are in `facts.sql`), a renamed key column, large tables, and anything inside the program.
