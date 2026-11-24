# Schema changes: every case

Status: needs-triage (belongs to `strategy.md`; a proposal, nothing is implemented)

Every way the shape of a source table, of its definition or of its target can change, what happens today and what is proposed. The list is meant to become the list of tests.

**Basis** says how sure a line is:

- `PG`: tried against Postgres 16 on 2026-11-24 with `facts.sql` in this directory.
- `code`: read in `src/rowvioli/load.py`.
- `desk`: reasoned, not run.
- `open`: not known. Somebody has to try it before the line counts.

The rules are in `strategy.md` and are cited here as "rule 4". "With a log" means a table with a key and a change log; without one a run adds columns and changes keys by itself and nothing else (rule 1).

## A. Columns come and go

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| A1 | New column | added to mirror and log; one `U` per row that has a value | the same, and an `I` in `columns__log` | code |
| A2 | New column, empty in every row | added, no row changes | the same | code |
| A3 | New column, and a consumer has a prepared `SELECT *` | the consumer's statement fails once with `cached plan must not change result type` | the same; it is Postgres's, and worth a line in `docs/target.md` | PG |
| A4 | New column, and a consumer's view says `SELECT *` | the view does not get it (documented) | the same | code |
| A5 | Column dropped, nobody built on it | fails for ever: `column city is missing in the source` | with a log: leaves the mirror, stays in the log, and the log gets one `U` per row that had a value; the mirror's rows are not rewritten (rule 3). Without a log: stops as today | code, desk |
| A6 | Dropped, and a view, materialized view, SQL-standard function, row security policy, trigger `OF column`, publication with a column list or generated column reads it | fails as A5 | fails with Postgres's detail, which names the object; nothing published | PG |
| A7 | Dropped, and an index or a `CHECK` uses it, also together with other columns | fails as A5 | Postgres drops them without a word, the whole index even if it has other columns. The run looks first and writes them into the note: `index i2 (name, city) went with it` | PG |
| A8 | Dropped, and a PL/pgSQL function, a BI tool or a program reads it | fails as A5 | nobody can know; it breaks at the consumer's next call. `columns__log` says since when. Whoever needs to be asked builds a view | PG |
| A9 | Dropped, and a consumer has a `GRANT` on that column | fails as A5 | the grant goes with the column and is not back when the column returns. Noted. Grants on the table are untouched | PG |
| A10 | Dropped column is a key column | fails: `a key column is not in the source` | the same; a person names the new key (C3) | code |
| A11 | Comes back with the same type | (cannot happen: A5 never passed) | the mirror gets it again, the log column continues, one `U` per row with a value | desk |
| A12 | Comes back with a type of the same family | | as A11; the type is widened only when a value needs it (rule 4) | desk |
| A13 | Comes back with a type of another family | | the log keeps the old values as `city__<run>`, a new `city` begins (rule 2) | desk |
| A14 | `text` → `integer` → `text` | | two retired log columns; the third does not continue the first | desk |
| A15 | Comes back with the same name and type but another meaning | | cannot be told apart, it continues; the gap in `columns__log` is the only sign | desk |
| A16 | Dropped and added again between two runs | invisible; rows whose values differ are `U` | the same | desk |
| A17 | Columns reordered | nothing, columns go by name | the same | code |
| A18 | New column named `_op`, or `_run`, `_loaded_at`, `_valid_from`, `_valid_to` with a log | fails for ever; `log = false` frees four of them, nothing frees `_op` | the same. A source that gains such a column stops this table, and there is no way to leave a column out. Open point of its own | code |
| A19 | New column whose name is a retired one (`city__812`) | | fails and says so; a person renames the log column | desk |
| A20 | Name longer than 63 bytes | the staging table gets the cut name and every later step sees that; a key naming the long column fails with `has no column`. Two names equal in their first 63 bytes: not tried | fail and name the column, and both if two collide | PG, code, open |
| A21 | Two columns that differ only in case (`City`, `city`) | two columns, both kept | the same | PG |
| A22 | The source delivers one name twice (CSV header, a query) | | open | open |
| A23 | Hundreds of drops and adds on one table over the years | | Postgres counts dropped columns towards its limit of 1600 per table. The `ADD` then fails; the reason names the way out (rewrite the table by dump and restore) | PG |
| A24 | Renamed, rows otherwise unchanged | fails as A5 | proven by the data (rule 6): renamed in mirror and log, no row written, the proof in the ledger's note. A consumer's view keeps working and keeps its own column name | PG, desk |
| A25 | Renamed, and rows changed in the same interval | fails as A5 | the proof looks only at rows that did not change otherwise. If none is left or one differs: a drop and an add, unless the definition says `renamed` | desk |
| A26 | Two renamed in one run | fails as A5 | each gone column needs exactly one candidate; those without are a drop and an add | desk |
| A27 | Renamed and retyped in one run | fails as A5 | same family: still a rename, and the type goes by rule 4. Another family: a drop and an add | desk |
| A28 | A column renamed, and a new one takes its old name, in one run | wrong data unnoticed if the types match: the new values load under the old name | proof would need comparing every old column with every new one. Not proposed: the rows are right, only the history of two columns is joined wrongly; rows show mass `U` | desk |
| A29 | Two columns swap names | invisible as a change of schema; every row is `U` | the same. No loader sees it | desk |
| A30 | One column split into two, or two merged | fails as A5 | a drop and adds | desk |
| A31 | Only the case of a name changes | fails as A5 | another name in Postgres: A24 or A25 | PG |

## B. Types

Families: the exact numbers (`smallint`, `integer`, `bigint`, `numeric`); the floats (`real`, `double precision`); `date` and `timestamp`. Every other type is a family of its own.

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| B1 | `integer` → `bigint` | fails: `has changed its type` | nothing while every value fits `integer`; the ledger notes the source's `bigint`. When one does not fit, mirror and log are altered, and Postgres rewrites both under an exclusive lock | PG, code |
| B2 | `numeric` gets more digits before the point | mirror keeps its type and loads while the values fit (decision 49) | the same, for every family; altered when a value needs it, without a rewrite | PG |
| B3 | `numeric` gets more digits after the point | as B2 | as B2, with a rewrite | PG |
| B4 | A type gets narrower (`bigint` → `integer`, fewer digits) | fails, or loads while values fit (`numeric`) | nothing; `source_type` changes in the ledger | desk |
| B5 | `integer` → `numeric` | fails | same family: as B1 | PG |
| B6 | `timestamp` ↔ `timestamptz` | fails | another family. With a log: the old values are retired in the log, a new column begins, a `U` per row. Without a log: stops. Postgres would alter it without a rewrite, but what the values mean depends on a time zone setting | PG, desk |
| B7 | `date` → `timestamp` | fails | same family: as B1 | PG |
| B8 | `integer` → `text`, `text` → `integer`, `boolean` ↔ `integer` | fails | another family. With a log: as A13. Without: stops | desk |
| B9 | `varchar(40)` → `varchar(80)`, `char` ↔ `varchar` | invisible: the driver delivers `text` (decision 28) | invisible, also to the ledger: Arrow carries no length. The one change of a declared type that leaves no trace | code, desk |
| B10 | Types change because the driver or rowvioli changed, the source did not | fails per table (0.4 did this with `json`) | does not stop (rule 8): the run acts by the rules and records `by = reader` with both versions. Two workers with different drivers retire a column with every run; all workers of a target run the same drivers | desk |
| B11 | A cast under `columns` in the definition changes | fails | by the same rules; the ledger says `by = definition` | code, desk |
| B12 | Fields inside a `jsonb` column change | rows are `U` | the same; no change of schema | desk |
| B13 | An array or struct changes its element type | fails | another family | desk |
| B14 | Enum, domain or user type in the source gets new values | arrives as text; invisible | the same | open |
| B15 | More than 38 digits | unconstrained `numeric` (decision 49) | the same | code |
| B16 | A timestamp gets finer than microseconds | | open what is lost today | open |
| B17 | Same value, another text form (`1.0`, `1.00`) | row is `U` (open point) | the same; not a change of schema | code |
| B18 | Collation, encoding or padding changes in the source | invisible; rows may be `U` | the same | desk |
| B19 | A type changes while the column is empty in every row | fails | by the rule; nothing to lose | desk |

## C. Keys

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| C1 | **No key, then a key is named** | fails: `the key ['id'] differs from the mirror's primary key []`; a person drops the mirror | the run replaces the mirror as a whole once more, adds the primary key, and the log begins with every row. The old rows may hold the key twice, so the key cannot go on first | code, desk |
| C2 | Key taken away, a log exists | fails and names the way | the same: the log would end, and the program does not end a log (rule 5) | code |
| C3 | Key taken away, no log | fails | primary key dropped, and `NOT NULL` with it, which Postgres leaves behind on the old key columns; from then on replaced as a whole | PG, code |
| C4 | Another key, a log exists | fails; a person drops mirror and log and loses the history | mirror replaced as a whole; primary key replaced, and the `NOT NULL` Postgres leaves on old key columns dropped; the log gets a `D` per old row and an `I` per new one; the history view has a branch per key, cut by run (rule 5) | PG, desk |
| C5 | Another key, no log | fails | primary key replaced | desk |
| C6 | Same key columns in another order | fails: the lists differ | nothing: the same rows are the same rows | code |
| C7 | Key column widened (`integer` → `bigint`) | fails | nothing while the values fit; then altered in place. A consumer's foreign key does not block it and keeps its own narrower type | PG |
| C8 | Key column gets a type of another family | fails | stops: whether `'007'` and `7` are one row, the program cannot say | desk |
| C9 | Key column renamed | fails | `renamed` in the definition makes it a rename and the key stays the same key (rule 6). Without it: another key, C4 | desk |
| C10 | The key occurs twice or is null in the source | fails with that reason | the same; where the connector can read the source's primary key, the reason names it | code |
| C11 | The source changes its primary key, the named key still identifies | nothing | nothing. Proposed later: the ledger notes the source's key, so the difference is at least on record | desk |
| C12 | A consumer's foreign key points at the mirror, or a view groups by its primary key, and the key changes | | Postgres refuses to drop the primary key and names the object; the run stops | PG |
| C13 | The value of a key changes in the source (7 becomes 8) | a `D` and an `I` | the same; identity is the key | code |
| C14 | The new key includes a column the old log rows do not have | | no matter: each stretch of the log is read with its own key | desk |
| C15 | Key changed by hand on the mirror | fails | the primary key is put back; the log was written under the definition's key all along. Recorded with `by = hand` | desk |

## D. Change log and history

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| D1 | `log = false`, later switched on | the log begins with every row | the same | code |
| D2 | Log exists, then `log = false` | fails and names the way | the same: the program does not end a log | code |
| D3 | Log dropped by hand | the next run begins a new one | the same; the first `_loaded_at` in the log shows it | code |
| D4 | A log column dropped or retyped by hand | fails if it does not fit | the one rule for the log: a missing column is added (its old values are gone, by hand), a wider one stays | desk |
| D5 | History view dropped or replaced by somebody | recreated by the next run | the same | code |
| D6 | A consumer's view reads the history view, and a log column is renamed or retyped | | the history view is dropped and created for every such change, so a consumer's view on it stops the run whichever column it reads. Postgres names the view | PG, desk |
| D7 | Somebody asks for the values of a dropped column | gone, if the recipe of `docs/loading.md` was followed | in the log and in the history view | desk |
| D8 | A log of 10⁸ rows and a type change that rewrites | | minutes under an exclusive lock, when a value first needs the wider type. Not measured. If it outlasts `max_seconds` the run is rolled back and tries again for ever; the reason has to say so | open |

## E. Tables

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| E1 | Source table dropped | fails with the driver's message; the mirror stays and ages | the same. Nothing is ever dropped for a table that is gone | code |
| E2 | Source table renamed | fails as E1 until a person changes the name in the definition. That makes a new table for rowvioli (it knows a table by source and source name); with `target_table` set to the old name its first run finds the old mirror and log and continues them if key and columns fit | the same; the ledger goes by the target name and continues too | code |
| E3 | Dropped and created again with other columns | | the rule, column by column, in one run; `max_delete_share` may stop it first | desk |
| E4 | Emptied | stops: zero rows, or `max_delete_share` | the same | code |
| E5 | Taken out of the definition and put back later | mirror and log are found and continued | the same; what changed meanwhile arrives as one run. The ledger shows no gap, the runs do | desk |
| E6 | Target name changed | recipes of decision 46 | the same. A run that finds ledger rows with its table's id under a name that is no table any more closes them with `by = hand` and enters its columns under the new name with `by = found` (rule 7). The keys the log was written under travel with the log (rule 5), so the history view stays right | code |
| E7 | The table moves to another system (new ERP), same target name | | by the rules. Expect other-family types and so retired columns, since another driver delivers | desk |
| E8 | The source object is a view whose definition changes | | as any change of columns | desk |
| E9 | A mirror name is taken over from a table that was already there | taken over (`docs/target.md`) | its columns enter the ledger with `by = found` | code, desk |
| E10 | New table in the source | not seen; `rowvioli list` prints it for a person | the same, on purpose | code |
| E11 | First run after this is installed, existing mirrors | | every column enters the ledger with `by = found`; the ledger's history begins there, later than the log's | desk |
| E12 | A table stuck on `missing in the source` when stage 2 arrives | | resolves itself with the next run if the table has a log and the log has the column; a column only the mirror has stops as G1, a table without a log stops as today | desk |

## F. Sources without a catalog (files, REST)

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| F1 | A column is missing in one file, one page or one run | fails | empty, not gone. The mirror keeps the column | code, desk |
| F2 | A header is renamed | fails | a new column; the old one is empty from then on. Nothing is proven for a source without a catalog; `renamed` in the definition makes it a rename | desk |
| F3 | Columns reordered in a CSV with a header | nothing | nothing | code |
| F4 | A guessed type flips (`42`, then `N/A`) | fails | stops, with the hint to pin the type under `columns` | desk |
| F5 | A guessed type widens within its family | fails | widened | desk |
| F6 | A new file of a pattern has one more column | added, if all files have it | added; the other files' rows have it empty | desk |
| F7 | Delimiter, quoting or encoding changes | wrong columns or the reader's error | the same: not a change of schema, and nothing here guards against it but `max_delete_share` and the key check | desk |
| F8 | CSV without a header | | open | open |

## G. The target, by hand or by consumers

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| G1 | Somebody adds a column to a mirror | fails for ever: `is missing in the source` | stops: `column x of the mirror is not in the change log, so it is not known to be from the source` (rule 3). Never dropped | code |
| G2 | Somebody drops a column the source still has | added again; a `U` per row | the same, recorded with `by = hand`; the log column continues | desk |
| G3 | Somebody widens a type in the mirror | fails | the mirror stays, the log is widened to it, recorded with `by = hand` | desk |
| G4 | Somebody changes a type to another family | fails | stops and says so | desk |
| G5 | Somebody adds `NOT NULL`, a `CHECK`, a default or a foreign key to a mirror | the run fails with Postgres's message when a row violates it | the same: it is a contract, and it holds | desk |
| G6 | A consumer makes the mirror a parent of other tables | | a dropped column leaves the children too | PG |
| G7 | A consumer replicates the mirror onwards | | Postgres blocks the drop only if the publication lists columns. Otherwise the subscriber breaks, unseen from here. Publish with a column list | PG |
| G8 | The worker does not own the mirror | `ADD COLUMN` fails with Postgres's message | the same for every change | desk |
| G9 | A consumer reads for a long time | the change waits 10 s, then the run fails and comes back after its pause | the same | code |
| G10 | Every other reader during a change | waits from the `ALTER` to the end of publishing | the same, and longer where a table is rewritten | desk |
| G11 | The target is restored from a backup | | mirror, log and ledger are from one moment and fit; the next run brings the difference | desk |
| G12 | Dump and restore, or a major upgrade of Postgres | | nothing changes; a restore resets the count of A23 | desk |
| G13 | Somebody edits `columns__log` | | its owner can. See "Not proposed now" in `strategy.md` | desk |

## H. Timing

| # | Case | Today | Proposed | Basis |
|---|---|---|---|---|
| H1 | The source is altered while a run reads it | the columns are taken once before reading; a batch that differs fails in the driver, nothing is published, and the next run sees the new shape | the same | code |
| H2 | The shape changed, and the run fails for another reason | nothing published | nothing published, nothing recorded; the next run sees the same difference | PG |
| H3 | Several changes in one run | fails on the first | all in one transaction, one row each in `columns__log` | desk |
| H4 | Changes pile up while a table fails for days | | the same as H3 | desk |
| H5 | `apply` changes the key while a run loads | the run publishes under the key it read at its claim; nothing checks it (decision 53 guards the name only), and the next run fails the key check | the run publishes under the key it read; the next run finds the difference and handles it (C4) | code |
| H6 | The worker dies during the change | the transaction is gone | the same | PG |
| H7 | The shape changes, and the source is empty | stops on zero rows if the mirror has rows | the same; the change is carried when rows are back | code |
| H8 | The clock is set back between two runs | rows of the log in the wrong order (decision 40) | the same for the ledger | code |

## I. What no loader can see

Said plainly, because a list that claims everything is not believed.

- The meaning of a column changes, name and type stay (euros become cents).
- Declared lengths, `NOT NULL`, defaults, foreign keys, indexes and comments of the source. A mirror has none of them, so their changes leave no trace (B9).
- Collation, encoding, time zone settings of the source.
- Two changes between two runs that cancel each other.
- Names that are swapped (A29), or a name reused in the same run a column was renamed (A28).
- Who changed the source. That is in the source's own audit.

## Open lines

Not tried: A22 (one name twice), B14 (enum and domain types), B16 (timestamps finer than microseconds), F8 (CSV without a header), the second half of A20 (two names that collide at 63 bytes), and D8 (how long a large log is locked). The first five are one small test each against the program as it is, and stage 0 of the strategy; D8 is a measurement in `bench/`, run when the owner asks.
