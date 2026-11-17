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

Staging table and diff are TEMP tables on the control connection. They have no fixed name in the target and disappear with the connection.

Bookkeeping in the schema `_rowvioli`:

```
sources   id, name, type, parallel, options, connection (ciphertext), key_id, enabled
tables    id, source, source_table, target_schema, target_table, key, max_age, at, timezone, log, max_delete_share, max_seconds,
          options, enabled, loaded_at, attempted_at, attempts, requested_at, reason
runs      run, table, worker, started_at, finished_at, status,
          rows_read, inserted, updated, deleted, reason, definition
status    view over tables: age, due_at and status, computed on every query
meta      schema_version, max_running, definition (hash of the definition last applied)
```

- `sources` and the first line of `tables` are the definition. Only `apply` writes them. A table row carries the settings a table may override, with the source's filled in.
- The second line of `tables` is what the workers experienced, plus `requested_at`.
- `runs` is a log: one row per run. Nothing reads it to decide anything.
- `status` is what people look at. It shows a table as `new`, `loading`, `ok` or `failed`, with the `reason` of a failure in a column of its own. A reason is one line: the driver's own message without its wrapper (`IO:`, `NOT_FOUND:`), traceback or the paths of a traceback. When the driver gave none, it says so and names the step. A table whose run died shows as `failed` with the reason `worker lost`.
- Progress is computed there too, for example `loading, 485,000 of about 1,000,000 rows`: while a table is loading, `rows_written` shows its rows so far and `rows_last_run` the rows read by its last successful run. The holder of the table lock is in `pg_locks`, its rows so far are in Postgres' own `pg_stat_progress_copy`. A worker writes nothing for it. `rows_written` is empty for a role that is neither the workers' role nor a member of `pg_read_all_stats`.

## History

Today's state is read from the mirror. What changed when is in the change log, and every row of it says when: `_loaded_at` is the moment its run published, the same `now()` that goes into `loaded_at`. Next to the log stands the view `<target table>__history`, which reads nothing but the log and gives every version of a row with the time it was valid.

**A change log that exists is complete.** Replaying it from its first row gives the mirror, always. A log that is created begins with every row of the mirror as `I` (for a table on its first run that is the diff; for a mirror that was there before, for example after `log = false` was taken away, it replaces the diff, while the run still reports its diff counts). A run that would leave the log behind its mirror fails instead ([Checks before publishing](loading.md#checks-before-publishing)). So the history is either complete from its first moment or there is none.

Example: customer 7 moves and customer 9 is deleted between two runs. The time is the time of the run, which is the time consumers first saw the change. It is never a time of the source.

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

On a long history the view is fast for one key and slow for one moment, measured on a log of 499 000 rows ([section 13](measurements.md#13-the-history-view-on-a-long-change-log)). A person who asks for the versions of one key may create an index, which the program never does: `CREATE INDEX ON raw_erp.customers__log (customer_no, _loaded_at)` took such a query from 8.9 to 0.1 ms. For one moment the view takes the time of the whole view (305 ms there) and no index helps; the same moment asked of the log directly took 117 ms, 2.6 times less:

```sql
SELECT customer_no, city
  FROM (SELECT DISTINCT ON (customer_no) * FROM raw_erp.customers__log
         WHERE _loaded_at <= '2026-11-13 07:59:00+00' ORDER BY customer_no, _loaded_at DESC) l
 WHERE _op <> 'D';
```

## Comparing in the target

Staging table and mirror sit next to each other in the target. One query finds the differences and writes them into a small TEMP table. Publishing then touches only these rows.

```sql
-- deleted: in the mirror, no longer in the staging table
SELECT 'D', m.customer_no, m.name, m.city
FROM raw_erp.customers m
WHERE NOT EXISTS (SELECT 1 FROM stage s WHERE s.customer_no = m.customer_no)

UNION ALL

-- inserted or updated: in the staging table, missing or different in the mirror
SELECT CASE WHEN m.customer_no IS NULL THEN 'I' ELSE 'U' END, s.customer_no, s.name, s.city
FROM stage s LEFT JOIN raw_erp.customers m ON m.customer_no = s.customer_no
WHERE m.customer_no IS NULL
   OR ROW(s.customer_no, s.name, s.city) IS DISTINCT FROM ROW(m.customer_no, m.name, m.city);
```

- **Row comparison instead of a hash.** `IS DISTINCT FROM` compares column by column and treats nulls correctly.
- **Columns are named explicitly.** `ROW(...)` compares by position. After a column has been added, the order in mirror and staging table can differ, so the program generates the column lists by name. `ROW(s.*)` would be wrong.
- **One pass.** Postgres reads both tables once and joins them on the key. The cost grows linearly with the number of rows.
- **Composite keys** only add columns to the join condition.
- **Without a key** there is no comparison and no change log. The transaction deletes all rows of the mirror and inserts the staging table. Consumers never see an empty table in that case either. The run counts the rows written as inserted and the rows that were in the mirror as deleted.

The comparison is safe although it runs before the transaction: as long as the run holds the table lock, no other run changes the mirror.

Publishing itself:

```sql
BEGIN;
INSERT INTO raw_erp.customers__log (_run, _loaded_at, _op, customer_no, name, city)
SELECT :run, now(), _op, customer_no, name, city FROM diff;                 -- unless log = false
DELETE FROM raw_erp.customers m USING diff d
 WHERE d._op IN ('D','U') AND d.customer_no = m.customer_no;
INSERT INTO raw_erp.customers SELECT customer_no, name, city FROM diff WHERE _op IN ('I','U');
UPDATE _rowvioli.tables SET loaded_at = now(), attempts = 0 WHERE id = :table;
UPDATE _rowvioli.runs SET status = 'ok', finished_at = now(), inserted = ..., updated = ..., deleted = ...
 WHERE run = :run;
COMMIT;
```

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

-- 3. If the total is below max_running: take the lock of the most overdue table
--    whose source is below its parallel, and count the attempt.
SELECT pg_try_advisory_lock(:source, :table);
UPDATE _rowvioli.tables SET attempted_at = now(), attempts = attempts + 1, reason = NULL WHERE id = :table;
INSERT INTO _rowvioli.runs (run, "table", worker, started_at, status) VALUES (:run, :table, :me, now(), 'running');

COMMIT;  -- releases only the counting lock from step 1, the table lock stays
```

- **Step 1 prevents overtaking.** Without it, two workers could read "three of four" at the same time and both take a table.
- **The count cannot drift.** If a worker dies, its lock disappears from `pg_locks` and no longer counts. Nobody has to book anything back.
- **The same view detects dead runs.** A run recorded as `running` whose table lock is missing is dead. Nobody has to act on that: the table becomes due again when its pause is over.
- **Order when finishing.** A run first records its result and then releases the lock. The other way round, a finished run would briefly look like a dead one. The one exception is a run ended after `max_seconds`: the worker kills it first and writes the reason afterwards, so it briefly shows as `worker lost`.
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
| Target Postgres is unreachable | workers wait and retry. Nothing is loaded. | |

In no case does anything half-done become visible: a COMMIT needs a command from the worker, and the worker is gone by then.

The program sets on its own connections:

- Keepalive: `keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=3`, `tcp_user_timeout=60000` in the URL, so the worker notices a dead server
- The same for the server's side of the session, `tcp_keepalives_idle = 30`, `tcp_keepalives_interval = 10`, `tcp_keepalives_count = 3`, `tcp_user_timeout = 60000`, so Postgres notices a dead worker and frees its locks. Without them the server's default applies, two hours on Linux.
- `client_connection_check_interval = 2s`, so that Postgres looks for the client during a long statement too
- `lock_timeout = 10s` for adding a column, so that a long-reading consumer cannot block the run forever. The run then fails with `lock timeout` and loads after its pause; meanwhile new readers of that table wait behind it for up to 10 s.

The control connection must go to Postgres directly, or through a pooler in session mode, not through one in transaction mode. A command that opens the target reads `pg_backend_pid()` in two transactions, and when the two differ it fails with `a connection pooler in transaction mode is in front of the target; use session mode`. The check is a net with holes: a pooler with no other client keeps handing out the same server connection and passes it, and one that is busy is caught most of the time (84 of 100 checks with eight busy neighbours, [measurements](measurements.md#14-the-pooler-check-behind-pgbouncer-in-transaction-mode)). Whoever runs a pooler configures session mode and does not rely on the check.
