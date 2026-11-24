# Schema changes of sources: strategy

Status: resolved (the design behind `spec.md`; the spec holds where the two differ)

Every single case is in `cases.md`. The Postgres behaviour this builds on was tried with `facts.sql`. This is the sixth version: five rounds of review and a prototype are worked in, and the owner's decisions are at the end.

## The idea

1. **The mirror follows the source, wherever a change log keeps what was.** A column the source no longer has leaves the mirror and stays in the log with every value it had.
2. **A change of columns is a change of rows.** A column that comes or goes writes one `U` for every row that has a value in it, as a new column does today. So the log still replays to the mirror, and the history ends the version that had the value.
3. **The columns are mirrored like rows.** A table `_rowvioli.columns` lists the columns of every mirror and log, with its own `columns__log` and `columns__history`.

A person is needed where somebody built on a column, and Postgres knows where that is.

## One example

The source drops `city` and adds `region`. One run, one transaction:

```
before                       after the run
raw_erp.customers            raw_erp.customers
  id    integer                id      integer
  name  text                   name    text
  city  text                   region  text         added, as today
                                                    city: gone, as in the source

raw_erp.customers__log       raw_erp.customers__log
  id, name, city               id, name, city, region
                               one U per customer: city now empty, region filled

_rowvioli.columns__log
  _op  table              column  type  mirror  by      _run  _loaded_at
  U    raw_erp.customers  city    text  false   source  812   2026-11-24 02:00
  I    raw_erp.customers  region  text  true    source  812   2026-11-24 02:00
```

Had a consumer's view read `city`, Postgres would have refused the `DROP COLUMN`. The run fails, publishes nothing, and `status` says:

```
✘ raw_erp.customers  failed  column city is gone from the source, and view reporting.customers_by_city reads it
```

Who wants to be asked before a column changes builds a view on it. There are no contract files and no modes.

## The rules

### 1. Where a run acts by itself

Only on a table with a change log. A table without a key, or with `log = false`, has a dropped column's values nowhere but in the mirror, so there a dropped column or a type of another family stops the run, as today. Additions and changes of key are automatic everywhere: they lose nothing.

### 2. A column comes

If the log holds that name in another family, the log column is renamed to `<name>__<run>`. Then mirror and log get the column where they lack it, and rule 4 looks after its type. The diff writes a `U` for every row with a value in it. That covers "new", "came back" and "came back as something else".

### 3. A column goes

- The log has it: it is dropped from the mirror and stays in the log. The log gets a `U` for every row that had a value. The mirror's rows are not touched for that; `DROP COLUMN` is all it needs.
- The log does not have it: the run stops with `column x of the mirror is not in the change log, so it is not known to be from the source`. A run adds a column to mirror and log together, so a column only the mirror has was added by a person. This test needs no bookkeeping.
- Postgres refuses the drop because something reads the column: the run stops and names it.
- A source without a catalog (files, REST) has no columns that go: a column missing from the data is empty.

### 4. A type differs

Families: the exact numbers (`smallint`, `integer`, `bigint`, `numeric`); the floats; `date` and `timestamp`. Every other type is a family of its own, `text` and `timestamptz` too.

- **Same family: the target keeps its type while the values fit, and is widened when one does not.** This is decision 49, for every family. "Fits" is one test for all of them: cast to the target's type and back, and the value is the same. Widening alters mirror and log to the type that holds both: the larger integer; for `numeric` the larger number of digits on each side of the point, an integer counting as 5, 10 or 19 digits and none after the point, and plain `numeric` beyond what Postgres can declare; `timestamp`; `double precision`. A source that narrows a type changes nothing. The ledger notes the source's type from the first run that sees it.
- **Another family: the column goes and comes** (rules 3 and 2 in one run).
- **Another family stops instead** when the source has no catalog (a guessed type flipped: pin it under `columns`) or when the column is in the key. A changed reader does not stop (rule 8).

### 5. A key differs

The key is named in the definition. Compared as a set, after renames (rule 6): the same columns in another order are the same key.

- **Another key, or a first key:** the run replaces the mirror as a whole, as it does for a table without a key, drops the primary key, drops the `NOT NULL` Postgres leaves on old key columns that are not in the new key, and adds the new primary key. In that order: the old rows may hold the new key twice. A log that exists gets a `D` for every old row and an `I` for every new one; a log that does not exist begins with every row, as today.
- **The history view** has one branch per key, joined with `UNION ALL`. The `D` and `I` rows of the change carry the same moment, so a branch is cut by `_loaded_at` and `_op`: up to that moment and its `D` rows, and from its `I` rows on. Not by `_run`: run numbers begin again when `_rowvioli` is rebuilt (decision 40). One branch over the whole log gives wrong rows (tried: a row whose `tenant` changed under the key `id` never ends under the key `id, tenant`).
- **The log says under which keys it was written.** The keys and the moments they changed are kept with the log itself, as the comment on its column `_op`, and the view is built from that. The history needs nothing in `_rowvioli` (decision 40), and the comment goes along when a person renames or moves the three objects, and through dump and restore. Not as the comment on the table: people and catalogue tools write those. A run that renames or retires a log column (rules 2 and 6) rewrites the comment in the same transaction, since it names the key columns. A log without the comment has had one key. If the comment is gone or unreadable while the ledger records a change of key, the run stops and does not build the view with one branch. The ledger records a change of key too, for the auditor; the view does not read it.
- **Replaying** the log gives the mirror from the last change of key on. Decision 40 says "from its first row"; that sentence changes.
- **Key taken away:** with a log the run stops, as today, since the log would end. Without one the primary key is dropped.
- **The primary key was changed by hand** and the definition's did not change: the primary key is put back. The log was written under the definition's key all along.
- **The named key no longer identifies a row:** the run stops, as today. Only a person can say what identifies a row.

### 6. A rename

One column gone and one come in the same run, same family. Without anything else that is rules 3 and 2. It is a rename instead, in mirror and log, with no row written, when

- **the data prove it.** One query over the mirror's old column and the staged new one, joined by the key, over the rows whose other columns did not change: all of them equal, at least 20 of them, at least 5 distinct values, exactly one candidate for the column, and the new name free in the log. The numbers are a proposal and deliberately strict, since a false proof makes a consumer's view read another column without a word. A source without a catalog has no column that goes, so nothing is proven there;
- **or the definition says it**: `renamed = { town = "city" }` at the table. Optional. It works on every table, with or without a log, and is what makes a renamed key column possible. It acts only when `city` is gone and `town` has come; while the source still delivers `city` it does nothing, so it may stay in the definition.

A consumer's view survives a rename in Postgres and keeps its own column name.

### 7. The ledger

`_rowvioli.columns`, one row per column of a mirror or its log, keyed by target schema, table and column:

| Field | Meaning |
|---|---|
| `type` | type in the target |
| `source_type` | type as the connector delivered it |
| `key` | position in the key, or empty |
| `mirror` | whether the mirror has the column; `false` for one that lives on in the log only |
| `was` | the name it had before a rename or a retirement |
| `by` | `source`, `definition`, `reader`, `hand` or `found` |
| `note` | what went with it: indexes, checks and column grants Postgres dropped without a word; the numbers of a proof |
| `id` | the table's id in `_rowvioli.tables`; not part of the key |

`columns__log` and `columns__history` are what `<table>__log` and `<table>__history` are for rows, with the same `_op`, `_run`, `_loaded_at`, `_valid_from`, `_valid_to`. Written in the publishing transaction and nowhere else.

- **Names.** The key includes the column's name, so a rename is a `D` and an `I` joined by `was`, and a retired column is a new row `city__812` with `was = city` and `mirror = false` beside the row `city`, whose type changes. To follow one column through its names, a reader walks `was`.
- **By hand.** Before a run acts it compares the ledger with the catalogue. What differs was changed by a person and is recorded with `by = hand`, dated when it was noticed, not when it was done. A table that keeps failing or is not loaded records nothing; its reason in `status` says what stops it.
- **Found.** The first run after this arrives finds no rows and enters every column with `by = found`.
- **A target renamed.** A run that finds rows with its table's `id` under a name that is no table any more closes them (`D`, `by = hand`) and enters its columns under the new name with `by = found`. That also happens when a mirror was dropped by hand and built anew under another name. Rows of a name that still is a table stay: they are true of that table.
- **Rights.** Auditors read `columns__history` and need no other right in `_rowvioli`.
- The ledger is not bookkeeping that may be thrown away. It is part of what is kept.

### 8. The reader changed

A new driver or a new rowvioli can deliver other types, or leave a column out, for a source that did not change. `_rowvioli.runs` gets the version of program and driver; the connector says its driver's version, which is new in its contract. A run whose versions differ from the table's last successful run, or whose last successful run has none, acts by the rules like any other and records what it does to the columns with `by = reader` and both versions in the note. It does not stop (decided by the owner).

### 9. The flow of a run

Today a run stages, checks, diffs and publishes, and the diff compares the columns of the staging table by name. That diff does not see a column that went, takes a renamed one for a new one, and fails comparing `text` with `integer`. So:

1. **Stage**, as today.
2. **Plan.** The check compares staging table, mirror, log and key and writes down what this run does to the columns: renames, columns that go, log columns to retire, types to widen, the key. Everything that stops a run by rule stops here, before anything is written.
3. **Diff, by the plan.** Over the columns of the mirror and of the staging table together, empty where one side lacks a column, a renamed column compared with its new name, a retired one never compared with its successor: both are called `city`, so the diff reads the old one under its retired name.
4. **Publish**, one transaction as today, in this order:
   - lock mirror, log and history view in one statement with `NOWAIT`, and try again for up to ten seconds, when the plan holds anything but an added column. A run that waits must not hold a lock: a consumer joining history and mirror takes them in its own order, and Postgres would end one of the two;
   - drop the history view, when the plan holds anything but an added column: Postgres alters no column a view uses;
   - the plan: renames, retirements, added and dropped columns, widenings, the key;
   - the diff into the mirror (not the rows that differ only in a column that went) and into the log (all of them);
   - the history view;
   - the ledger;
   - `pg_notify('rowvioli_schema', …)`, which Postgres delivers on commit only;
   - the check of the target name (decision 53), last as before.

The step a run is in is already part of a failure's reason. Widening gets a step of its own, so a run ended after `max_seconds` says that it was rewriting, and which column.

## What stops a run, in one list

| Reason | Way out |
|---|---|
| A view, materialized view, SQL function, policy, trigger, publication with a column list, generated column or foreign key depends on what would change. A view on a history view depends on every column of it | the consumer changes it |
| A column of the mirror is not from the source | a person drops it |
| No change log, and a column is gone or of another family | as today, by hand |
| The named key does not identify a row, is taken away with a log, or a key column is of another family | a person, in the definition |
| The note of the keys on the log is gone while the ledger records a change of key | a person puts it back; the reason gives the text |
| A guessed type flipped | pin it under `columns` |
| A name the log needs is taken or too long; 1600 columns are used up | by hand; the reason says how |
| A rewrite, or the log rows of a dropped column, outlast `max_seconds` | raise it once; the reason names the step |

## What an auditor asks

| Question | Answer |
|---|---|
| Which columns and types did the table have on 1 March? | `columns__history` with `mirror` and the same condition on `_valid_from`, `_valid_to` as for rows |
| When did `amount` change, from what, in which run, caused by what? | one row of `columns__log`, with `by` |
| Under which definition was it loaded? | `runs.definition` of that `_run`: a hash, and in the bookkeeping, so a question for the operator |
| Which rows were loaded under which columns? | `_loaded_at` is the same `now()` in both logs |
| Were values lost when the column went? | no: they are in the log and the history, and the version that had them ends at that moment |
| Was the target changed by hand? | recorded by the next run that publishes, with `by = hand` and the moment it was noticed; a change that stops the table is in `status` instead. Who it was is Postgres's to say (`log_statement = ddl`, pgaudit) |
| What did the source call the type? | `source_type`, as far as Arrow carries it; a declared length is not carried |
| Can the record be altered? | by the role that owns it. See "Not proposed" |

## Against the market

Verified from vendor documentation unless marked [U] (from memory, not checked).

| | Market | Here |
|---|---|---|
| Dropped column | Airbyte keeps it and fills NULL for ever; Fivetran the same [U]; Snowflake's schema evolution does not handle it | the mirror says the truth, the log keeps the values, the history ends the version |
| Type change | dlt: a second column; Airbyte: errors per row, then a refresh; Estuary: table dropped and reloaded by default; Delta: opt-in, one-way | widened when a value needs it; another family is a second column in the log only; never a reload |
| Rename | none of the tools read detects one | proven by the data, or stated in the definition |
| Change and data in one transaction | not where DDL commits on its own (Snowflake, BigQuery) | one transaction |
| Log of changes | dlt: versions with a hash; Snowflake: a note on the column that a manual change clears; Fivetran: in its UI [U] | a table with history, read like any mirror |
| Changes by hand | nowhere on record | recorded by the next run |
| Who is affected | nowhere tied to the change | the failing run names the object |
| Approval | modes per connector or connection | the view is the contract |
| Notification | not tied to the change | `pg_notify` in the same transaction |
| Tamper evidence | none found | none |

The market is ahead in finding new tables by itself. rowvioli names tables on purpose.

## Price

- **A dropped column, and a type of another family, cost one log row per row**, as an added column does today, and on a very large table that can outlast `max_seconds`. A changed key costs two per row and rewrites the mirror.
- **Widening can rewrite mirror and log** under an exclusive lock (`integer` → `bigint`, more digits after the point, `date` → `timestamp`). It happens when a value needs it, not before. Not measured on a large log.
- **A seam nobody recorded.** A person who changes a primary key and the definition by hand and keeps the log leaves a log with two keys and no note of it. No rule finds that.
- **A changed reader costs rows.** After an upgrade that delivers a type in another family, every affected table writes a log row per row once. Two workers with different drivers retire a column with every run until somebody sees the notifications: all workers of a target run the same drivers.
- **Old log columns pile up** (`amount__812`) where a source changes families often, and Postgres counts dropped columns towards its 1600 per table.
- **Indexes, checks and column grants on a dropped column go with it.** The ledger says which.
- **More kinds of object stop a run than today**, and a view on a history view stops changes of any of its columns.
- **`_rowvioli` gets its first migration** (version 3 to 4); the program has none today and refuses another version.

## What it removes

- The recipes "a column was dropped", "more digits", "a type was tightened" and "the key changed" in `docs/loading.md`, for tables with a change log.
- The price of decision 49, and the exception in the code for `numeric` alone.
- Decision 17. Decision 31's rule that a changed key stops.

## Stages

Each is useful alone. "Who implements" follows `CLAUDE.md`; Opus reviews each.

| | What | Who implements |
|---|---|---|
| 0 | The five untried cases as tests of the program as it is (A20, A22, B14, B16, F8). Migration of `_rowvioli`; program and driver version in `runs` | Sonnet |
| 1 | The ledger and `pg_notify`. No change of behaviour | Sonnet |
| 2 | The plan and the diff by it (rule 9); a column goes and comes back (rules 1 to 3) | Opus |
| 3 | Types (rules 4 and 8); the connector's contract gets the driver's version | Opus |
| 4 | Keys (rule 5) | Opus |
| 5 | Rename (rule 6) | Opus |

No stage needs the ledger to work; it is the record, not a part of the mechanism.

## Decided by the owner (2026-11-24)

1. Decision 17 is reversed: the mirror follows the source.
2. Something reads a dropped column: the table stops.
3. No switch for the old behaviour.
4. Rename with proof is wanted; stating a rename in the definition is allowed as long as it stays optional.
5. `pg_notify` is in. `COMMENT ON COLUMN` with the source's type is not, until somebody asks.
6. A changed reader does not stop a table; the change is recorded with `by = reader`.

## Tried

`experiments/09_schema_changes.sql` plays the rules against Postgres 16 by hand, ten claims, every assertion `ok`: a column goes, comes back, comes back in another family; the test for "fits" and the widened types; a changed key with the history at five moments; a first key; the proof of a rename, also where it must not prove; the locks, also on a view; `pg_notify`; the ledger. Not tried: large tables, the objects of consumers that stop a change (those are in `facts.sql`), a renamed key column, and anything inside the real program.

## Not proposed

- **Tamper evidence** (each row of `columns__log` carrying a hash of the one before). One column, addable later. First the usual answer: the logs owned by a role the worker is not.
- **Leaving a column out** of a database source. Today a source column named `_op` stops its table for good (cases A18).
- **Finding new tables.**
- **A dry run.** The failed run says what would have happened and has published nothing.
