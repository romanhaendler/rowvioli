# Target names and history: a table says where it lives, and its change log says when

Status: resolved

## Problem Statement

Two things are missing in the target.

**A table cannot say where it lives.** The schema is set per source (`target_schema`, default `raw_<name>`), and the name of a target table is always the last part of the source table's name. `dbo.Customers` and `sales.Customers` of one source both become `customers`, `apply` fails, and the definition offers no way out. A source cannot spread its tables over several schemas, and several sources cannot share one, because a schema belongs to exactly one source (decision 35).

**Nobody can ask what a table looked like last Tuesday.** The change log holds every change, but a row of it carries only the number of its run. The time is in `_rowvioli.runs`, which is bookkeeping, may be cleaned up, and needs rights on `_rowvioli`. The README promises that validity periods "can be computed as a view"; no such view exists and its speed was never measured (`docs/open-points.md`, "Not verified"). And the log itself cannot be trusted for it: one that was switched on late, or off for a while, lacks rows and nothing says so.

## Solution

Two sentences carry it.

**A table says where it lives, and the definition gives no target name twice.** `target_schema` may stand at a table as well as at the source, and a table may name its `target_table`. The rule "a schema belongs to exactly one source" is replaced by the rule it stood for.

```toml
# sources/erp.toml
[erp]
type = "odbc"
max_age = "1h"
target_schema = "raw_erp"                      # the default for its tables, as today

[erp.tables."dbo.Customers"]
key = ["customer_no"]                          # raw_erp.customers, as today

[erp.tables."sales.Customers"]
key = ["customer_no"]
target_table = "sales_customers"               # raw_erp.sales_customers

[erp.tables."hr.Staff"]
key = ["staff_no"]
target_schema = "raw_hr"                       # raw_hr.staff
```

One schema per source, one schema for everything, or one schema per schema of the source: all three are a matter of the definition and none is built in. Whoever sets nothing sees no change.

**A change log that exists is complete, and it says when.** Every row of a change log gets `_loaded_at`, the moment its run published. Replaying a log from its first row gives the mirror, always; a run that could not keep that true fails instead. Next to the log stands a view `<target table>__history` that reads nothing but the log and gives every version of a row with the time it was valid.

```
raw_erp.customers__log                            raw_erp.customers__history
_run | _op | _loaded_at  | id | city              _valid_from | _valid_to   | id | city
  40 | I   | 11-10 06:00 | 7  | Bonn              11-10 06:00 | 11-12 06:00 | 7  | Bonn
  40 | I   | 11-10 06:00 | 9  | Essen             11-10 06:00 | 11-12 06:00 | 9  | Essen
  42 | U   | 11-12 06:00 | 7  | Cologne           11-12 06:00 |             | 7  | Cologne
  42 | D   | 11-12 06:00 | 9  | Essen
```

The table as it was at a moment is one condition on that view:

```sql
SELECT * FROM raw_erp.customers__history
 WHERE _valid_from <= '2026-11-11' AND (_valid_to > '2026-11-11' OR _valid_to IS NULL);
```

The time is the time of the run, which is the time consumers first saw the change. It is never a time of the source.

## User Stories

### A table says where it lives

1. As a definition author, I want to set `target_table` at a table, so that two source tables with the same last name part can both be loaded.
2. As a definition author, I want to set `target_schema` at a table, so that one source can fill several schemas.
3. As a definition author, I want `target_schema` at the source to stay the default for its tables, and `raw_<name>` the default for the source, so that an existing definition means what it meant.
4. As a definition author, I want several sources to be allowed the same `target_schema`, so that I can keep all mirrors in one schema if I choose to.
5. As a definition author, I want `target_table` refused at the source, so that a setting that can only belong to one table is not written where it would apply to all.
6. As a definition author, I want `apply` to fail when two tables of the definition get the same target name, whichever sources they belong to, to name both, and to say that `target_table` at one of them is the way out, so that two source tables never load into one mirror and the error tells me what to type.
7. As a definition author, I want the names of the change log and of the history view to count in that check, so that a table named `customers__log` cannot meet the change log of `customers`.
8. As a definition author, I want that check to need no target, so that `rowvioli list` and a review of the definition find the mistake before anything is applied.
9. As a definition author, I want a source table that was renamed in the source to keep its mirror and its history when I rename it in the definition and give it the old `target_table`, so that a rename in the source is one edit and no SQL.
10. As a definition author, I want a table that left the definition to hold no name any more, so that the definition alone says who owns a name. Whoever takes the name over meets the checks before publishing (schema, key, share of deleted rows) on the first run.
11. As a definition author, I want `apply` to refuse a `target_schema` longer than 63 bytes, a target table longer than 54 bytes, an empty name, and the schema `_rowvioli`, so that Postgres never cuts a name and no mirror lands in the bookkeeping.
12. As a definition author, I want a table of a file source that sets no `target_table` to lose its extension as today, so that the default does not change.
13. As an operator, I want the schema of a table created on its first run wherever the definition puts it, so that I never create a schema by hand.
14. As an operator, I want `rowvioli status`, the status view and the lines of a worker to show the target name the table really has, so that what I read is what I can query.
15. As a definition author, I want `apply` to say one line for every table whose target name it changes, with the old and the new name and the sentence that the old tables stay where they are, so that a rename never leaves a stale mirror behind without my knowing.
16. As an operator, I want a changed target name to move nothing in the target, and the README to give the three statements that rename mirror, change log and history view, so that rowvioli never renames or drops a table by itself (as with a changed key).

### A change log that exists is complete

17. As a consumer, I want a change log that is created for a mirror that already exists to begin with every row of the mirror as `I`, so that the history is complete from the moment the log begins and not only for rows that changed since.
18. As a consumer, I want a run that would publish without writing to a change log that exists (because `log = false` was set, or the key was taken away) to fail and name the log to drop, so that a log never falls silently behind its mirror and its history never shows versions as current that are not.
19. As a consumer, I want a run that would build a new mirror next to a change log that is still there (the mirror was dropped or renamed without it) to fail and name the log, so that two histories are never laid on top of each other.
20. As an operator, I want both failures to carry a reason that says what to drop or rename, so that the fix is one statement and the next run loads.

### The change log says when

21. As a consumer, I want every row of a change log to carry `_loaded_at`, the moment its run published, so that the log answers "when" without another table.
22. As a consumer, I want `_loaded_at` of a run's rows to equal the table's `loaded_at` after that run, so that the log and the status view tell one time under one name.
23. As a consumer, I want a view `<target table>__history` for every table with a change log, with `_valid_from`, `_valid_to` and all columns of the table, so that I can read validity periods without writing a window function.
24. As a consumer, I want the current version of a row to have an empty `_valid_to`, so that "valid now" is `_valid_to IS NULL` and every client can read the column.
25. As a consumer, I want a deleted row to end the validity of its last version and to appear no further, so that the view holds versions that existed and nothing else.
26. As a consumer, I want a row that was deleted and came back to show two periods with a gap, so that the view tells what was the case.
27. As a consumer, I want the table as it was at a moment to be one condition on `_valid_from` and `_valid_to`, written out in the README, so that point in time needs no second view and no function, and two tables can be read at the same moment with the same condition.
28. As a consumer, I want the view to read only the change log, so that the right to read the log is the right to read the history, and nothing in `_rowvioli` is needed.
29. As an operator, I want `_rowvioli.runs` to stay a log that nothing reads to decide anything, so that I can clean it up without losing a time.
30. As a consumer, I want a column the source adds later to appear in the view, empty for the versions before it, so that the view follows the table.
31. As a consumer, I want the view to exist whenever the change log does, also after somebody dropped it, so that I never have to ask for it.
32. As an operator, I want a run to touch the view only when it creates it or adds a column, so that an ordinary run takes no lock on the view and never waits behind a reading consumer.
33. As a definition author, I want a source table with a column named `_loaded_at`, `_valid_from` or `_valid_to` refused the way `_op` and `_run` are, with a reason that says so, so that a name of rowvioli never meets a name of the source.
34. As a consumer, I want no history view for a table without a key or with `log = false`, so that a view never promises what the log cannot give.
35. As an operator, I want one measurement on a long history in `docs/measurements.md`: the whole view, the view at one moment, the view for one key, and the same moment written directly against the log, so that I know the price and the README can name the faster query if there is one.

### Documents

36. As a reader of the README, I want "Defining a source" to show `target_schema` and `target_table` at a table and the one rule about names, so that I learn both settings where I learn the others.
37. As a reader of the README, I want "Target schema" to show the change log with `_loaded_at`, the history view, and the query for a moment, so that the example with customers 7 and 9 ends in an answer.
38. As a reader of the README, I want one place that says what a person does by hand: rename the three tables after a changed name, drop log and view after `log = false` or a changed key, so that every failure reason of this spec has its statement there.
39. As a reader of the decisions, I want one new decision that replaces decision 35 and says why names instead of schemas are checked, and one that says why the time is in the log, why history is a view and why a log is complete or absent, so that nobody reintroduces a rule that is already covered.
40. As a reader of the glossary, I want "Target table" and "Change log" to say what is true now and a term for the history view, so that the vocabulary stays binding.

## Implementation Decisions

### Names

- **`target_schema` becomes a setting of the table**, like `max_age`: set at the source or at the table, and the table's row carries it with the source's filled in. `_rowvioli.tables` gets the column, `_rowvioli.sources` loses it. The run's facts, the status view and everything that prints a target name read it from the table's row.
- **`target_table` is a setting of the table only.** Without it the name is derived as today. A name that is set is taken as written and quoted wherever it is used, like a derived one.
- **One rule replaces decision 35: the definition gives no target name twice.** A table takes three names in its schema: its own, `…__log` and `…__history`. The definition is checked as a whole when it is read, across sources, without a target. The error names both tables and `target_table` as the way out.
- **Only the definition owns names.** A table that left the definition is disabled and holds nothing. The check `apply` makes today against the schemas of disabled sources goes away and nothing replaces it. Whoever takes a name over finds the old mirror on the first run, and the checks before publishing decide: a different table fails on its columns or its key, the same table under a new source name simply continues, with its change log.
- **The limit for a target table is 54 bytes**, for every table: 63 minus `__history`. Today it is 58. One number, whether or not the table has a key or a log. `_rowvioli` is refused as a `target_schema`, and a name must not be empty.
- **A changed name moves nothing, and `apply` says so.** Before it writes, `apply` reads the target names the tables of the definition have in the target and prints one line per table whose name changes. The next run finds no mirror under the new name and builds one, with every row as `I`. Whoever wants to keep mirror and history renames mirror, change log and history view by hand before that run; the README gives the statements next to the sentence about a changed key.

### History

- **`_loaded_at` is written in the publishing transaction with `now()`**, the same value that goes into `tables.loaded_at`, and it has the same name for that reason. (`at` is taken: it is the load time of the definition.) A new change log is created with it: `_run`, `_op`, `_loaded_at`, then the columns of the mirror. `_run` stays as the pointer to the run and orders nothing.
- **A change log that exists is complete.** Three cases keep it true, and they are the whole rule:
  - *The log is created.* It begins with every row of the mirror as this run publishes it, as `I`. For a new table that is the diff; for a mirror that was there before, it replaces the diff.
  - *The log exists and the run writes to it.* The diff is appended, as today.
  - *The log exists and the run would not write to it, or would build a new mirror beside it.* The run fails in the checks before publishing, with a reason that names the log and says to drop it with its view, or to rename both with the mirror.
- **The history view orders by `_loaded_at`**, not by `_run`: run numbers start again when `_rowvioli` is created anew, the clock does not. Two runs of one table never publish at the same moment, because the table lock makes them follow each other.
- **The shape of the view.** `_valid_from` is the `_loaded_at` of a row, `_valid_to` the `_loaded_at` of the next row with the same key, and rows with `D` are left out after that was computed. `_valid_from` and `_valid_to` come first and the table's columns after them, so that a new column can be appended by replacing the view. The periods are half-open: a version is valid from `_valid_from` up to but not including `_valid_to`. An open period is null, not `infinity`: drivers and BI tools disagree about `infinity`, and null is what readers of validity columns know.
- **The view exists whenever the log does.** A run that writes to a change log creates the view if it is missing and replaces it when it added a column to the log. Looking whether it is there takes no lock. No other run touches it.
- **`_loaded_at`, `_valid_from` and `_valid_to` are reserved** for a table with a key and a change log, in the existing check for `_op` and `_run`.
- **No index on the change log is built.** The measurement decides whether the README names one that a person may create, and whether it names a faster query for one moment written against the log. A run creates neither.

### Both

- **Schema version 3, no migration.** Nothing has been published yet (owner, 2026-11-13): the change log is simply extended and every volume is built anew. Nothing detects or converts a change log without `_loaded_at`.
- **Two new decisions are appended to `docs/decisions.md`** under the next numbers. The first changes decision 35 (marked there as changed, as decision 4 is by 31) and names what was rejected: a fixed layout such as one `staging` schema, a prefix or a name pattern, renaming by `apply`, and names that stay taken by tables the definition no longer has. The second names what was rejected for history: reading the time from `runs`, a function `as_of(table, time)` in place of a view, a second view per moment, a history table kept by the run (decision 4 stands), `infinity` for an open period, and a log that may have gaps.
- **Documents.** README: "Defining a source" (settings table and the bullet about names), "Comparing in the target" (the publishing example writes `_loaded_at`), "Target schema" (log, view, the query for a moment, the bookkeeping columns), "Checks before publishing" (the reserved names, the two new failures, what a person does by hand), "Commands" (`apply` fails on a name given twice and says a changed name), "The target" (a consumer's role needs the right to read the view; default privileges on tables cover views). GLOSSARY: "Target table", "Change log", new "History". `docs/open-points.md`: the view leaves "Not verified"; the known limits below are added. `docs/measurements.md`: section 13.

### Who implements

Before implementing a ticket, decide which model it needs and take the smallest that fits (CLAUDE.md, "Choosing the model"). Estimate, to be checked again per ticket:

| Work | Model |
|---|---|
| Names: the two settings, the one rule in the definition, the column moving from `sources` to `tables`, the line `apply` says | Sonnet. Specified and mechanical. |
| History: `_loaded_at`, the three cases of a complete log, the view, the reserved names | Opus. The view's SQL, the place of the two new failures among the checks and the moments the view may be touched need judgement. |
| The measurement on a long history | Sonnet. A bench script next to the existing ones and a section of numbers. |
| Documents and the two decisions | Sonnet. |
| Review of the whole at the end | Opus. |

## Testing Decisions

- **The existing seam, nothing new.** Tests start the commands as real processes against real PostgreSQL in Docker and look only at what a user sees (`.scratch/v0.1/spec.md`, "Testing Decisions"). What a user sees now includes the tables and views in the target under the names the definition gives, and the rows of the history view.
- **A good test** states one sentence of this spec and would pass if the load were rewritten. It reads the view and the mirror with SQL; it does not compare the text of the view's definition.
- **No simulated clock.** Where a test needs two moments it runs twice and reads the `_loaded_at` values the runs wrote.

What is tested:

1. A table with `target_table` and a table with `target_schema` are loaded where the definition says, and the schema is created (prior art: `tests/test_run.py`).
2. Two tables of one source with the same last name part load side by side once one of them sets `target_table`.
3. Two sources with the same `target_schema` and different table names are applied and loaded.
4. `apply` fails, names both tables and names `target_table` when two tables get the same target name: within a source, across sources, and through `__log` or `__history` (prior art: `tests/test_apply.py`, where the existing tests for a shared `target_schema` are rewritten to the new rule).
5. `apply` refuses `target_table` at the source, a target table longer than 54 bytes, an empty name and the schema `_rowvioli`.
6. A source table renamed in the definition with its old `target_table` keeps its mirror: the next run reports the changes only, and the history view shows the versions from before the rename.
7. A different table that takes over the name of a table that left the definition fails its first run on the columns or the key, and the old mirror is unchanged.
8. `apply` says a line with the old and the new name when a loaded table's target name changes, and none when nothing changes.
9. `rowvioli status` and the lines of a worker show the name the table has (prior art: `tests/test_status_command.py`, `tests/test_work.py`).
10. After two runs with an update and a delete between them, the history view shows the periods of the example above: the old version ends where the new begins, the current one is open, the deleted row has an end and no further version; `_loaded_at` of the second run's rows equals `loaded_at`.
11. The condition for a moment between the two runs returns the mirror as it was after the first run, and for a moment after the second run the mirror as it is.
12. A row that is deleted and comes back shows two periods with a gap.
13. A column added in the source appears in the view, empty in the older versions (prior art: the new-column tests in `tests/test_checks.py`).
14. A table loaded with `log = false` and switched to a log later has a history that returns the whole mirror for a moment after that run.
15. A table with a change log that is switched to `log = false` fails its next run with a reason that names the log; after the log and the view are dropped it loads.
16. A mirror dropped without its change log fails the next run with a reason that names the log; after the log is dropped it loads and the history begins anew.
17. A history view that was dropped is there again after the next run that publishes.
18. A table without a key and a table with `log = false` from the start have no change log and no history view.
19. A source column named `_loaded_at`, `_valid_from` or `_valid_to` fails the run with a reason that names it.
20. The view can be read by a role that has rights on the table's schema and none on `_rowvioli`.

Not tested: the speed of the view (it is measured, not asserted), and a clock that jumps backwards.

Disk space: the harness's rule stands. Free disk and Docker usage are checked before and after, and containers and volumes are removed after the session. The measurement fills a long change log; its volume is removed when the numbers are written down.

## Out of Scope

- Renaming or moving a mirror, a change log or a view by `apply` or by a run. A person does it, and `apply` says when it is due.
- A fixed layout: one `staging` or `raw` schema, a prefix, a name pattern. The two settings express each of them. The word staging stays the name of the TEMP table of a run.
- `rowvioli list` proposing a `target_table` for names that would meet. The error of `apply` names the way out.
- A time of the source, or one common moment for two tables. Each table has the moments of its own runs.
- A function `as_of`, a view per moment, a materialised history.
- An index on the change log, unless the measurement asks for one, and then as advice.
- History for tables without a key or with `log = false`.
- Pruning the change log.
- Migrating a target of schema version 2, or a change log without `_loaded_at`.

## Further Notes

- The owner asked for this on 2026-11-13: ways to set the name and the schema of a table in the target, and views to look at a table point in time. Decided in the conversation: several schemas per source must be possible; the time of the run is enough, a time of the source can never be delivered; the history must work without `_rowvioli.runs`; nothing is published yet, so the log is extended and the volumes are rebuilt.
- The owner then left the open points to this spec, with the measure "what a user would expect, and what makes the library top notch". Decided on that measure, each with what tipped it:
  - **A table that left the definition holds no name.** The first draft kept the name taken. A user who renames a table in the source expects one edit in the definition; the kept name would have asked for a hand-deleted row in the bookkeeping, for which no command exists. The definition is the truth everywhere else (decision 21, `status` shows enabled tables only), and the danger that matters, two tables loading into one mirror, is two enabled tables, which the definition check covers. It also removes a check instead of adding one.
  - **`apply` says a changed name.** The alternative, known from other tools, is a stale table under the old name that consumers keep reading without any failure.
  - **A change log is complete or absent.** A history that is silently wrong is worse than none: a late log would miss every unchanged row, a log switched off would show outdated versions as current. Failing is the project's own answer ("it fails rather than guess", and a changed key already asks for a person).
  - **`_loaded_at` instead of `_at`.** `at` is the load time in the definition and the glossary; the column holds exactly `tables.loaded_at`.
  - **The view orders by `_loaded_at`**, although the brainstorm said `_run` orders safely. Rebuilding `_rowvioli` restarts the run numbers, and without a migration that is how a target is upgraded.
  - **`__history`, `_valid_from`, `_valid_to`, null for open.** The names readers of validity periods already know.
  - **54 bytes for every table.** One number is easier to say than one per kind of table, and the limit was one number before.
  - **Schema per source stays the default.** It is what comparable tools do, it keeps names short, and it allows rights per source.
- Known limits, to go into `docs/open-points.md`:
  - Dropping a change log needs `CASCADE` or dropping the view first.
  - A clock set back between two runs of one table by more than the time between them would put their rows in the wrong order.
  - A mirror and a change log that are renamed away leave nothing behind, but a log left under a name the definition no longer has keeps a history view that nobody updates.
- The owner's rule for this repo applies: one carrying idea, no pile of rules. The measure is that the README replaces the sentence "a schema belongs to exactly one source" by "the definition gives no target name twice", and needs one paragraph, one invariant and one query for history.
