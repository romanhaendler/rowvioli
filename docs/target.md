# Inside the target

What rowvioli keeps in the target: the bookkeeping, the mirrors, their change logs and history; how a run compares and publishes there, how Postgres counts what is running, and what happens when something fails.

## Target schema

Per target table:

```
raw_erp.customers          mirror: columns of the source, primary key = key
raw_erp.customers__log     change log, unless log = false
  _run, _op, _loaded_at    run, I, U or D, and the moment the run published
  ... all columns
raw_erp.customers__history view over the change log: every version of a row
  _valid_from, _valid_to   from and until (not included); empty while current
  ... all columns
```

A change log has a comment on its column `_op`: the keys it was written under, as JSON, for example `[{"key": ["id"]}]`. The history view is built from it ([History](#history)).

Staging table and diff are TEMP tables on the control connection. They have no fixed name in the target and disappear with the connection.

The schema may be one that other things read already. Beside every mirror with a key stand `<name>__log` and `<name>__history` in the same schema, and `log = false` leaves them out. A table that is there under the name of a mirror is taken over when its columns, their types and its primary key are those of the source: the first run deletes the rows the source does not have, and the change log begins with the rows that are left. Otherwise the run fails and names the difference.

**A consumer that may read only the mirrors cannot tell a mirror that stopped from a quiet source.** After a failed run the mirror keeps its last good state and looks exactly like one whose source has not changed; only `_rowvioli.status` shows the difference. The consumer needs two grants for that, and nothing else in the schema opens with them:

```sql
GRANT USAGE ON SCHEMA _rowvioli TO consumer;
GRANT SELECT ON _rowvioli.status TO consumer;
```

`SELECT target_table, status, age, reason FROM _rowvioli.status` then shows `failed` with the reason (for example `customers.csv: no such file in data`), or `ok` with the age of the last load.

**A view of the consumer's own over a mirror keeps its columns.** `CREATE VIEW mine AS SELECT * FROM raw_erp.customers` is expanded when it is created, since Postgres fixes the columns of a view then. When the source gains a column, the mirror gets it with the next run and `mine` does not: replace the view (`CREATE OR REPLACE VIEW`, which may add columns at the end) or drop it and create it again. A statement prepared on a mirror, such as `SELECT *`, fails after its columns change, by a new one, one that goes or a widened type (`cached plan must not change result type`), and it fails on every call until it is prepared again; a pool that keeps its prepared statements has to drop them. A reader that lists a mirror's columns (from `information_schema.columns`, say) and then selects them by name gets `column ... does not exist` when a run took one away in between, and reads the list again.

**A consumer's view or foreign key stops a change and is named.** A run changes the columns of a mirror by itself ([Columns](loading.md#columns)): a column the source drops leaves it, a type is widened, a key changes. Where an object of a consumer depends on what would change, Postgres refuses, the run fails with a reason that says which column would have changed and names the object, and nothing is published. The consumer changes or drops the object, and the next run goes on. So whoever wants to be asked before a column changes builds a view on it. Two things follow:

- A view on a mirror stops what happens to a column it reads: a widening and the column's going. It does not stop a type that is kept while every value fits, nor a change of key, unless it depends on the primary key (one that groups by the key and reads other columns); a foreign key to the mirror stops a change of key.
- A view on a **history view** stops changes to any column of that history view, because a run drops the history view and creates it again whenever it carries out more than the adding of columns: a column that goes, a type widened, a column renamed or retired, a change of key. A new column replaces it in place and does not stop. The grants on the history view stay: the run reads them before it drops the view and gives them again after it has created it, in the same transaction, each with its grant option, and a grant on a renamed column under the column's new name. The view's owner is the worker's role, as before.

A column that is renamed in the source and proven so by the data ([Columns](loading.md#columns)) is renamed in mirror and change log, and a view on it keeps working under its own column name.

Bookkeeping in the schema `_rowvioli`:

```
sources   id, name, type, parallel, options, connection (ciphertext), key_id, enabled
tables    id, source, source_table, target_schema, target_table, key, max_age, at, timezone, log, max_delete_share, max_seconds,
          options, enabled, loaded_at, attempted_at, attempts, requested_at, reason
runs      run, table, worker, started_at, finished_at, status,
          rows_read, inserted, updated, deleted, reason, definition, program_version, driver_version
status    view over tables: age, due_at and status, computed on every query
meta      schema_version, max_running, definition (hash of the definition last applied)
columns   the columns of every mirror and change log: see "The columns table"
columns__log, columns__history   its change log and history view
```

`schema_version` is 4. `rowvioli init` brings a target of version 3 to 4 and changes nothing else; a worker of 0.4.1 or older refuses version 4, and every command of this program but `init` and `status` refuses version 3 until `init` has run.

- `sources` and the first line of `tables` are the definition. Only `apply` writes them. A table row carries the settings a table may override, with the source's filled in.
- The second line of `tables` is what the workers experienced, plus `requested_at`.
- `runs` is a log: one row per run. Nothing reads it to decide anything.
- `status` is what people look at. It shows a table as `new`, `loading`, `ok` or `failed`, with the `reason` of a failure in a column of its own. A reason is one line: the driver's own message without its wrapper (`IO:`, `NOT_FOUND:`), traceback or the paths of a traceback. When the driver gave none, it says so and names the step. A table whose run died shows as `failed` with the reason `worker lost`: the view finds that nobody holds the table lock any more and no reason was written. The run that next claims the table sets the dead run's row in `runs` to `failed`, reason `worker lost`, with a `finished_at`.
- Progress is computed there too, for example `loading, 485,000 of about 1,000,000 rows`: while a table is loading, `rows_written` shows its rows so far and `rows_last_run` the rows read by its last successful run. The holder of the table lock is in `pg_locks`, its rows so far are in Postgres' own `pg_stat_progress_copy`. A worker writes nothing for it. `rows_written` is empty for a role that is neither the workers' role nor a member of `pg_read_all_stats`.

## History

Today's state is read from the mirror. What changed when is in the change log, and every row of it says when: `_loaded_at` is the moment its run published, the same `now()` that goes into `loaded_at`. A run that finds nothing writes no log row, so the newest `_loaded_at` of a log is the last change, not the last load; the last load is the `age` in `rowvioli status`. Next to the log stands the view `<target table>__history`, which reads nothing but the log and gives every version of a row with the time it was valid.

**A change log that exists is complete.** Replaying it from its last change of key (its first row, where the key never changed) gives the mirror, always, also after columns went or came. A log that is created begins with every row of the mirror as `I` (for a table on its first run that is the diff; for a mirror that was there before, for example after `log = false` was taken away, it replaces the diff, while the run still reports its diff counts). A run that would leave the log behind its mirror fails instead ([Checks before publishing](loading.md#checks-before-publishing)). So the history is either complete from its first moment or there is none.

Example: customer 7 moves and customer 9 is deleted between two runs. The time is the time of the run, which is the time consumers first saw the change. It is never a time of the source. Two changes of a row between two runs are one version, the last. A row that is deleted and inserted again between two runs is one `U`, or no change when it comes back as it was.

```
mirror  raw_erp.customers
 customer_no |  city
-------------+---------
           7 | Cologne

change log  raw_erp.customers__log
 _run | _op |          _loaded_at           | customer_no |  city
------+-----+-------------------------------+-------------+---------
    1 | I   | 2026-11-13 07:58:57.722619+00 |           7 | Bonn
    1 | I   | 2026-11-13 07:58:57.722619+00 |           9 | Essen
    3 | U   | 2026-11-13 07:59:06.861926+00 |           7 | Cologne
    3 | D   | 2026-11-13 07:59:06.861926+00 |           9 | Essen

history  raw_erp.customers__history
          _valid_from          |           _valid_to           | customer_no |  city
-------------------------------+-------------------------------+-------------+---------
 2026-11-13 07:58:57.722619+00 | 2026-11-13 07:59:06.861926+00 |           7 | Bonn
 2026-11-13 07:59:06.861926+00 |                               |           7 | Cologne
 2026-11-13 07:58:57.722619+00 | 2026-11-13 07:59:06.861926+00 |           9 | Essen
```

A version is valid from `_valid_from` up to but not including `_valid_to`. The current version has an empty `_valid_to`, and a deleted row ends its last version and appears no further. The table as it was at a moment is one condition on the view. Write the moment with its offset: the columns are `timestamptz`, and a time without an offset is read in the time zone of your session.

```sql
SELECT * FROM raw_erp.customers__history
 WHERE _valid_from <= '2026-11-13 07:59:00+00' AND (_valid_to > '2026-11-13 07:59:00+00' OR _valid_to IS NULL);
```

This returns customers 7 (Bonn) and 9 (Essen). A moment before the first load returns nothing: there was no mirror yet. The view exists whenever the change log does, and a column the source adds later appears in it, empty for the versions before. Both exist only for a table with a key and without `log = false`.

**Columns that go, come and change.** A column the source drops leaves the mirror and stays in the change log and the history view. The change log gets a `U` for every row that had a value in it, so the version that had the value ends at the moment the column went and the next one has it empty. A column that comes back continues its old column in the change log, empty for the versions in between. Where a column comes back with a type of another family, the change log's old column is renamed `<name>__<run>` (a retired column, here `city__812` for run 812), keeps its values, and a new column takes the name; the history view shows both. A type of the same family that is widened is widened in the change log too. A renamed column is renamed in the change log, so the history view shows it under its new name at every moment, also before the rename; the columns table keeps the old name for the moments before, and its row of the new name says the old one in `was`, which joins the two. The columns table says when each of this happened ([below](#the-columns-table)).

**A changed key.** The mirror is replaced as a whole under the new key, and the change log gets a `D` for every old row and an `I` for every new one, with the moment of the run. The history view then has one branch per key, joined with `UNION ALL`, each over its own stretch of the change log and partitioned by its own key: the stretch of the old key reaches up to the moment of the change and its `D` rows, the next begins with its `I` rows. The keys and the moments they changed are the comment on the change log's column `_op`, and the view is built from that comment and from nothing in `_rowvioli`:

```sql
SELECT col_description('raw_erp.customers__log'::regclass, (SELECT attnum FROM pg_attribute
        WHERE attrelid = 'raw_erp.customers__log'::regclass AND attname = '_op'));
-- [{"key": ["customer_no"]}, {"from": "2026-11-24T09:15:02.113845+00:00", "key": ["customer_no", "name"]}]
```

Every change log the program begins has the comment with its one key; one without it is from before this version (one key) or lost it. A person who drops or changes the comment makes the next run fail after a change of key, and the reason holds the text to put back (`COMMENT ON COLUMN "raw_erp"."customers__log"._op IS '...'`): it is the latest note `the change log's keys: ...` in `columns__log`. A comment that is not what the program wrote, a key that is no list, a `from` that is no moment or a column the change log does not have, counts as lost. A run that renames or retires a column of a key rewrites the comment in the same transaction. A change log from before this version may need the comment once: where the first run after the upgrade cannot tell whether a person or the definition changed the key ([A key](loading.md#columns)), its reason gives both comments, and the one a person puts there says the key the change log was written under.

A changed key costs two log rows per row, and the history before the change is read by the old key. Nothing before it is lost.

What changed in a period is a condition on the change log. An update shows the new values, a delete the last ones:

```sql
SELECT _op, customer_no, city FROM raw_erp.customers__log
 WHERE _loaded_at > '2026-11-13 07:59:00+00' AND _loaded_at <= '2026-11-13 07:59:10+00' ORDER BY customer_no;
```

This returns `U` for customer 7 (Cologne) and `D` for customer 9 (Essen).

On a long history the view is fast for one key and slow for one moment, measured on a log of 499 000 rows ([section 13](measurements.md#13-the-history-view-on-a-long-change-log)). A person who asks for the versions of one key may create an index, which the program never does: `CREATE INDEX ON raw_erp.customers__log (customer_no, _loaded_at)` took such a query from 8.9 to 0.1 ms. For one moment the view takes the time of the whole view (305 ms there) and no index helps; the same moment asked of the log directly took 117 ms, 2.6 times less:

```sql
SELECT customer_no, city
  FROM (SELECT DISTINCT ON (customer_no) * FROM raw_erp.customers__log
         WHERE _loaded_at <= '2026-11-13 07:59:00+00' ORDER BY customer_no, _loaded_at DESC) l
 WHERE _op <> 'D';
```

## The columns table

Which columns and types a mirror had at a moment, and what caused each change, is kept the way rows are: `_rowvioli.columns` is to the columns of the mirrors what a mirror is to its rows, `_rowvioli.columns__log` its change log and `_rowvioli.columns__history` its history view, with `_op`, `_run`, `_loaded_at`, `_valid_from` and `_valid_to` as for any change log; the history view carries `_run` and `_op` as well, so that who may read only it reads what changed and in which run. `_loaded_at` is that of the rows published in the same transaction, so a column's change and the rows loaded with it carry the same moment. The three are written by the publishing transaction only, for every table, with or without a key.

```
columns   target_schema, target_table, column     the key
          type          the type in the target
          source_type   the type as the connector delivered it
          key           the place in the key (1, 2, ...), empty if not a key column
          mirror        whether the mirror has the column; false for one only the change log has
          was           the name before a rename or a retirement
          by            source, definition, reader, hand or found
          note          see below
          id            the table's id in _rowvioli.tables, not part of the key
```

There is one row per column of a mirror and one per column only its change log has: a column that left the mirror (`mirror` false) and a retired column `<name>__<run>`.

- **`by` says what caused the change.** `source`: the source changed. `definition`: the definition did, with a type under `columns`, a `renamed`, a changed `key`, or a column taken out of a REST table's `columns` (every change a run makes to the columns of a REST table is `definition`, and so is every change of a column a table names under `columns`, one that comes included, and a pin taken out of a CSV, Excel or JSON column). `reader`: the change came with another version of the program or of the driver than the table's last successful run had, or that run had none, so it is not necessarily the source's; the note holds both versions (`program 0.4.1 to 0.5.0, driver duckdb 1.5.0 to duckdb 1.5.1`). `hand`: a person changed the mirror or its change log, and the next run that published found it. `found`: the first fill of a table, or the columns of a mirror renamed by hand under its new name; where the first fill is of a mirror that was there, such as the first run after the upgrade to version 4, what the run changed in it has its cause, and only what it found unchanged is `found`.
- **`note`** lists, for a column that left the mirror, the indexes, check constraints and column grants that Postgres dropped with it without a word (`index raw_erp.customers_city_idx, constraint city_check on table raw_erp.customers, the grant of SELECT to reader went with it`); for a rename the data proved, `proven by the data: 20 rows unchanged otherwise, 20 of them equal, 5 distinct values`; for a changed key `the change log's keys: ` and the comment on `_op`; for a primary key a person changed and the run put back, `the primary key (a) was put back to the definition's (b)`.
- **`source_type` is the type as staged**, not as the source named it: a `json` column arrives as `jsonb`, a `varchar(n)` as `text`, and a mirror that is wider than its source says why in the pair of `type` and `source_type`.
- **A change by hand is dated when it is noticed**, by the run that publishes next, and not at all while its table fails. A column that a person drops from the mirror and the run adds again is recorded as `hand`.

Which columns did the table have on 1 March? A column the mirror has is `mirror`; without that condition the change log's columns come too:

```sql
SELECT "column", type, "key" FROM _rowvioli.columns__history
 WHERE target_schema = 'raw_erp' AND target_table = 'customers' AND mirror
   AND _valid_from <= '2026-03-01 00:00:00+00' AND (_valid_to > '2026-03-01 00:00:00+00' OR _valid_to IS NULL)
 ORDER BY "column";
```

What changed in a table since a moment, in which run, by whom, and what the note says:

```sql
SELECT _valid_from, _run, _op, "column", type, mirror, was, "by", note FROM _rowvioli.columns__history
 WHERE target_schema = 'raw_erp' AND target_table = 'customers' AND _valid_from > '2026-03-01 00:00:00+00'
 ORDER BY _valid_from, "column";
```

`_op` is `I` for a column the record did not have and `U` for a change. A column a person dropped from mirror and change log, and every column of a mirror renamed by hand under its old name, is closed instead: its last version ends then (`_valid_to`) and none follows, so the query above does not list it; `columns__log` has it as a `D` row.

The reader of `columns__history` needs `SELECT` on that view and nothing else in `_rowvioli`, as for the history of a mirror ([Rights](operation.md#the-target)). With it the reader sees the columns of every table of the target, in every schema, and in the notes the names of the indexes and constraints that went with a column and of the roles that had a grant on it.

**The notification.** A run that records a change of columns, a key or a name notifies the channel `rowvioli_schema` in the transaction that publishes it, once per run, so a listener hears it at the COMMIT and never for a run that was rolled back. The payload is small and fixed: `{"schema" : "raw_erp", "table" : "customers", "run" : 812}`, as Postgres writes a JSON object. A listener reads what changed from the history view, `SELECT _op, "column", type, mirror, was, "by", note FROM _rowvioli.columns__history WHERE _run = 812`, which needs no right on `columns__log`. A column closed in that run, as above, is not among those rows; a listener that must hear of it reads `columns__log` with the same condition, which needs `SELECT` on it. It is not sent for a first fill where every column is `found`: a table's first fill is no change of columns. A first fill that changed a column, such as the first run after the upgrade on a table whose source dropped one, sends it. A change `by = hand` or `by = reader` is sent as well.

```sql
LISTEN rowvioli_schema;
```

## Comparing in the target

Staging table and mirror sit next to each other in the target. One query finds the differences and writes them into a small TEMP table. Publishing then touches only these rows.

```sql
-- deleted: in the mirror, no longer in the staging table
SELECT 'D', m.customer_no, m.name, m.city
FROM ONLY raw_erp.customers m
WHERE NOT EXISTS (SELECT 1 FROM stage s WHERE s.customer_no = m.customer_no)

UNION ALL

-- inserted or updated: in the staging table, missing or different in the mirror
SELECT CASE WHEN m.customer_no IS NULL THEN 'I' ELSE 'U' END, s.customer_no, s.name, s.city
FROM stage s LEFT JOIN ONLY raw_erp.customers m ON m.customer_no = s.customer_no
WHERE m.customer_no IS NULL
   OR ROW(s.customer_no, s.name, s.city) IS DISTINCT FROM ROW(m.customer_no, m.name, m.city);
```

- **Row comparison instead of a hash.** `IS DISTINCT FROM` compares column by column and treats nulls correctly.
- **Columns are named explicitly.** `ROW(...)` compares by position. After a column has been added, the order in mirror and staging table can differ, so the program generates the column lists by name. `ROW(s.*)` would be wrong.
- **One pass.** Postgres reads both tables once and joins them on the key. The cost grows linearly with the number of rows.
- **Composite keys** only add columns to the join condition.
- **`ONLY`** reads and deletes the rows of the mirror itself, never those of a table of a consumer's that inherits from it.
- **Without a key** there is no comparison and no change log. The transaction deletes all rows of the mirror and inserts the staging table. Consumers never see an empty table in that case either. The run counts the rows written as inserted and the rows that were in the mirror as deleted.

The comparison is safe although it runs before the transaction: as long as the run holds the table lock, no other run changes the mirror.

Publishing itself:

```sql
BEGIN;
INSERT INTO raw_erp.customers__log (_run, _loaded_at, _op, customer_no, name, city)
SELECT :run, now(), _op, customer_no, name, city FROM diff;                 -- unless log = false
DELETE FROM ONLY raw_erp.customers m USING diff d
 WHERE d._op IN ('D','U') AND d.customer_no = m.customer_no;
INSERT INTO raw_erp.customers SELECT customer_no, name, city FROM diff WHERE _op IN ('I','U');
UPDATE _rowvioli.tables SET loaded_at = now(), attempts = 0 WHERE id = :table;
UPDATE _rowvioli.runs SET status = 'ok', finished_at = now(), inserted = ..., updated = ..., deleted = ...
 WHERE run = :run;
COMMIT;
```

Where the plan holds more than added columns ([Columns](loading.md#columns)), publishing begins differently: it locks mirror, change log and history view in one statement with `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE NOWAIT`, tried again for up to ten seconds, so that a run never waits for a lock while it holds another and cannot deadlock with a consumer who reads them in another order. Then it drops the history view, carries out the plan (renames, retired columns, the key, columns that go, widened types), applies the diff, creates the history view again, writes the columns table, notifies on `rowvioli_schema` and ends with the check of the target name, as above.

## How Postgres counts

There is no counter that is incremented and decremented. What is counted are the locks that are actually held at this moment.

Every table lock has two numbers: that of the source and that of the target table. Postgres lists all held locks in the system view `pg_locks`. The number of tables of a source that are loading right now is the number of rows there carrying the number of that source. The number of all rows is what the target bears in total.

```sql
BEGIN;
-- 1. Only one worker at a time may count and claim.
SELECT pg_advisory_xact_lock(0, 0);

-- 2. Count: table locks held in this database, per source and in total.
SELECT classid AS source, count(*) FROM pg_locks
 WHERE locktype = 'advisory' AND classid <> 0 AND objsubid = 2 AND granted
   AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
 GROUP BY classid;

-- 3. If the total is below max_running: take the lock of a table that never loaded, else of
--    the most overdue table, whose source is below its parallel, and count the attempt.
SELECT pg_try_advisory_lock(:source, :table);
UPDATE _rowvioli.tables SET attempted_at = now(), attempts = attempts + 1, reason = NULL WHERE id = :table;
INSERT INTO _rowvioli.runs (run, "table", worker, started_at, status) VALUES (:run, :table, :me, now(), 'running');

COMMIT;  -- releases only the counting lock from step 1, the table lock stays
```

- **Step 1 prevents overtaking.** Without it, two workers could read "three of four" at the same time and both take a table.
- **The count cannot drift.** If a worker dies, its lock disappears from `pg_locks` and no longer counts. Nobody has to book anything back.
- **The same view detects dead runs.** A run recorded as `running` whose table lock is missing is dead. Nobody has to act on that: the table becomes due again when its pause is over, and the run that claims it then closes the dead run's row in `runs` as `failed` with the reason `worker lost`.
- **Order when finishing.** A run first records its result and then releases the lock. The other way round, a finished run would briefly look like a dead one. The one exception is a run ended after `max_seconds`: the worker kills it first and writes the reason afterwards, so it briefly shows as `worker lost`. A claim in that moment closes its row as `worker lost`; the worker's reason then replaces it in `runs`.
- **Number 0 is reserved.** It marks the counting lock. Sources get numbers from 1.

The prototype claimed this way with 6 workers of 4 slots, two sources with `parallel` 2 and 3, and `max_running = 4`. A probe every 20 ms never saw more than the limits, and both were reached. With the counting lock removed, the same test broke the total limit in 1 of 4 runs. Details in [docs/measurements.md](measurements.md#9-the-prototype).

## Failures

| What happens | Consequence | Lock released after |
|---|---|---|
| Worker crashes while Postgres waits for it | transaction discarded, run dead, retried after the pause | under 0.3 s (measured) |
| Worker crashes while Postgres is computing a statement or waiting for a lock | as above, as soon as Postgres notices the loss | under 4 s with a connection check every 2 s (measured), otherwise when the statement ends |
| Machine or network drops out | as above, detected through the server's TCP keepalive | about 60 s (62 s with a container's network cut, [measurements](measurements.md#11-a-worker-whose-network-is-cut)) |
| Source is unreachable for a moment | the run fails, the next one starts a minute later | right after |
| Source stops answering | the worker ends the run's process after `max_seconds` | right after |
| A table fails again and again | the pause doubles up to `max_age`. The status shows the reason and the number of attempts. | |
| A connector is not installed on a worker | the run fails with a reason that names the worker | right after |
| The target fails over to another node | connections drop, running loads end without publishing, the retry catches up | with the connection |
| An object of a consumer depends on a column, type or key that would change | the run fails and names the object, nothing is published | right after; the next run goes on once the object is changed |
| Target Postgres is unreachable | workers wait and retry. Nothing is loaded. | |
| Target Postgres restarts during a run | the run fails with `connection to the target lost`. `work` records it once the target is back, and loads on. `rowvioli run`, whose own connection is gone too, ends with the line `connection to the target lost` and exit code 1, and the status shows `worker lost` until the table's next run | with the connection |

In no case does anything half-done become visible: a COMMIT needs a command from the worker, and the worker is gone by then.

The program sets on its own connections:

- Keepalive: `keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=3`, `tcp_user_timeout=60000` in the URL, so the worker notices a dead server
- The same for the server's side of the session, `tcp_keepalives_idle = 30`, `tcp_keepalives_interval = 10`, `tcp_keepalives_count = 3`, `tcp_user_timeout = 60000`, so Postgres notices a dead worker and frees its locks. Without them the server's default applies, two hours on Linux.
- `client_connection_check_interval = 2s`, so that Postgres looks for the client during a long statement too
- `lock_timeout = 10s` for adding a column, so that a long-reading consumer cannot block the run forever. The run then fails with `lock timeout` and loads after its pause; meanwhile new readers of that table wait behind it for up to 10 s.

The control connection must go to Postgres directly, or through a pooler in session mode, not through one in transaction mode. A command that opens the target reads `pg_backend_pid()` on its connection, on a second connection, and on its connection again, before it claims anything; a run process leaves it to the worker that started it. Postgres gives every connection a server process of its own for its life, so the second connection never has the first one's, and one connection never changes it. A pooler in transaction mode hands a server process to whichever client asks next: an idle one hands the first connection's to the second, a busy one moves the first between its transactions, and a very busy one loses the driver's statement to another client (`SQLSTATE 26000` or `08P01`). Each of the three stops the command with `a connection pooler in transaction mode is in front of the target; use session mode or connect directly`. It was caught in every one of 400 checks with up to 16 busy neighbours ([measurements](measurements.md#14-the-pooler-check-behind-pgbouncer-in-transaction-mode)). Nothing is claimed through such a pooler: a table lock taken there would stay on a server process the pooler keeps, and the table would show `loading` until the pooler restarts.
