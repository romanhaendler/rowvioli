# rowvioli

> **Status 2026-11-12: version 0.1 is being built** ([spec](.scratch/v0.1/spec.md)). The model described here (a maximum age per table, definitions in the target, stateless workers) has been tried out as a whole in a throwaway prototype: every guarantee below held, and its findings are worked into these documents ([findings](.scratch/prototype/findings.md)). Measured besides: compare and publish as plain SQL, the row comparison on wide tables, the behaviour when a process is killed and a complete run through the ADBC driver. What is proven and what is not is listed in [docs/measurements.md](docs/measurements.md) and [docs/open-points.md](docs/open-points.md).

A program that mirrors tables from source systems into a PostgreSQL target. You say how old each table may be. Workers keep it that fresh, and consumers always see a complete state.

```toml
# sources/erp.toml
[erp]
type    = "postgres"
max_age = "1h"

[erp.connection]
url = "postgresql://reader:$ERP_PASSWORD@erp-db01/erp"

[erp.tables]
"public.customers" = { key = ["customer_no"] }
"public.items"     = { key = ["item_no"] }
"public.orders"    = { key = ["order_no"], max_age = "5m" }
```

```sh
export ROWVIOLI_TARGET_URL=postgresql://etl@pg01/dwh   # the target, for every command
rowvioli init               # once per target: creates the schema _rowvioli
rowvioli key new            # once per target: worker.key for the workers, worker.pub next to the definition
rowvioli apply sources/     # once per deployment: writes the definition into the target
ROWVIOLI_KEY_FILE=worker.key rowvioli work   # on any number of machines: keeps every table fresh
```

```
select source, source_table, max_age, age, status, reason from _rowvioli.status;

 source | source_table     | max_age | age    | status  | reason
--------+------------------+---------+--------+---------+-----------------------------------
 erp    | public.orders    | 5m      | 2m     | ok      |
 erp    | public.customers | 1h      | 1h 3m  | loading |
 erp    | public.items     | 1h      | 40m    | ok      |
 crm    | contacts         | 1d      | 3h     | failed  | 62 % of the rows would be deleted
```

That is the whole usage. `docker compose up` in [examples/quickstart](examples/quickstart) plays it with a source and a target. There is no schedule, no queue and no job. One table in the target is work list, state and monitoring at once.

Two ideas carry the design:

- **You state the freshness, not the time.** A table is due when it is older than its `max_age`. A worker takes the table that misses its target the most.
- **Postgres does everything that is hard.** The connection of a run is its lock and its sign of life. Postgres compares the rows, counts what is running and computes what is due. The program passes rows from the source to the target and never holds a whole table in memory.

## Contents

- [Guarantees](#guarantees)
- [Overview](#overview)
- [Defining a source](#defining-a-source)
- [When a table is loaded](#when-a-table-is-loaded)
- [A run](#a-run)
- [Comparing in the target](#comparing-in-the-target)
- [Target schema](#target-schema)
- [Workers](#workers)
- [How Postgres counts](#how-postgres-counts)
- [Failures](#failures)
- [Connections](#connections)
- [Commands](#commands)
- [Operation](#operation)
- [Connectors](#connectors)
- [Web UI](#web-ui)
- [Measurements](#measurements)
- [Further documents](#further-documents)

## Guarantees

- **Never a half-loaded or empty state.** For every table, consumers see the state before or after a run, nothing in between.
- **Never two runs on the same target table.** This holds across machines and workers.
- **Failed and dead runs are retried** without heartbeats or deadlines, after a pause that grows from one minute.
- **Bounded memory.** Per table, a worker holds only a few chunks of the size the connector delivers (about 16 MB with ADBC).
- **One flow for everything.** Initial load, follow-up load and tables without a key take the same path.

What it is not:

- Not a general scheduler. It knows how old a table may be and nothing else about time.
- Not a transformation tool. Columns arrive the way the source delivers them.
- Not a tool for targets other than PostgreSQL.

## Overview

The definition names every table and its maximum age. `rowvioli apply` writes it into the target. Workers know nothing but their connectors: they take the next due table from the target, load it and publish it in its own transaction.

```mermaid
flowchart LR
    subgraph Deploy[Deployment of the definition]
        D["sources/*.toml<br/>worker.pub"]
        E["environment<br/>ERP_PASSWORD=…"]
        A[rowvioli apply]
    end
    subgraph PG[Target Postgres]
        S[("_rowvioli.sources<br/>type, encrypted connection")]
        T[("_rowvioli.tables<br/>one row per table")]
        L[["table locks<br/>one per target table"]]
        M[("raw_erp.*<br/>mirrors and change logs")]
    end
    subgraph Workers[Workers, any number, all alike]
        W1[Worker 1]
        W2[Worker 2]
        Wn[Worker n]
    end
    Q[(Sources)]

    D --> A
    E --> A
    A -->|writes| S
    A -->|writes| T
    W1 -->|takes a due table| T
    W2 -->|takes a due table| T
    Wn -->|takes a due table| T
    Q -->|reads| W1
    W1 -->|loads| M
```

Whoever deploys the definition needs access to the target and nothing else: no driver, no route to a source. A worker needs no checkout, no configuration file and no address under which it can be reached.

The terms are defined in the [glossary](GLOSSARY.md).

## Defining a source

One file per source, by convention. It names the connector, the connection and every table.

```toml
# sources/erp.toml
[erp]
type          = "odbc"
target_schema = "raw_erp"
max_age       = "1h"
parallel      = 4

[erp.connection]
string = "Driver={ODBC Driver 18 for SQL Server};Server=sqlsrv01;Database=erp;UID=reader;PWD=$ERP_PASSWORD"

[erp.tables]
"dbo.Customers"  = { key = ["customer_no"] }
"dbo.Items"      = { key = ["item_no"], log = false }
"dbo.Orders"     = { key = ["order_no"], max_age = "5m" }
"dbo.OrderLines" = { key = ["order_no", "line_no"] }
```

What follows from it:

- Every listed table gets a target table in `raw_erp`. Nothing else is loaded. A new table in the source arrives when somebody adds its name.
- `dbo.Orders` is never older than five minutes, the other tables never older than an hour.
- At most four tables of this source load at the same time, across all workers.
- Every table with a key gets a change log, except `dbo.Items`, where it is switched off.
- The password is not in the file. `$ERP_PASSWORD` is filled in from the environment when `apply` runs. The whole connection block is then encrypted and stored in the target.

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `type` | source | | Connector: `postgres`, `odbc`, `file`, `rest`, or the name of an installed connector package. |
| `connection` | source | | Everything the connector needs to reach the source. The fields are defined by the connector. Values may contain `$NAME` placeholders. See [Connections](#connections). |
| `max_age` | source or table | | How old the mirror may get, for example `5m`, `1h`, `1d`. Required at source level. |
| `tables` | source | | The tables to load, by name. |
| `target_schema` | source | `raw_<name>` | Schema of the target tables. A schema belongs to exactly one source: `apply` fails if two share one. |
| `parallel` | source | 2 | Maximum number of tables of this source loading at the same time. |
| `key` | table | none | Columns that identify a row. Without a key the table is replaced as a whole. |
| `log` | source or table | on | Keep a change log. `log = false` switches it off. Tables without a key never have one. |
| `max_delete_share` | source or table | 0.5 | The run aborts if a larger share of the rows would disappear. Without a key: if the table would shrink by more. |
| `max_seconds` | source or table | 3600 | A hanging run is ended after this time. |

Any other key, at source or table level, is passed to the connector unchanged as an option, for example `path` for a REST connector. A table's option overrides the source's of the same name.

Nobody has to type 200 table names and keys. `rowvioli list erp` asks the source and prints them in this format, ready to paste. It is a helper for people. Nothing in the running system calls it.

## When a table is loaded

The target stores only facts per table. When a table is due is computed from them on every query.

| Fact | Meaning | Written by |
|---|---|---|
| `max_age` | allowed maximum age | `apply` |
| `loaded_at` | when the table was last published | the worker, inside the publishing transaction |
| `attempted_at` | when the last run began | the worker, when it claims the table |
| `attempts` | runs since the last success | the worker: plus one when claiming, zero on success |
| `requested_at` | when somebody asked for a load now | a person or another system |

```
due_at =  at once                       if never attempted
          requested_at                  if requested after the last run began
          loaded_at + max_age           if the last run succeeded
          attempted_at + pause          otherwise
```

- **Order.** A worker takes the table that is the most overdue measured against its own `max_age`. A five-minute table that is two minutes late overtakes hourly tables that are ten minutes late.
- **Retry.** After a run that did not succeed, the pause is one minute, then 2, 4, 8 minutes and so on, but never longer than `max_age`. A success resets it. A nightly table that fails at 02:00 is tried again at 02:01, 02:03, 02:07, 02:15, 02:31, 03:03 and so on.
- **A crash needs no bookkeeping.** The attempt was counted when the table was claimed and the success never came. The pause follows from that. A crashed worker and a failed check go through the same formula.
- **A changed `max_age` takes effect at once**, because nothing derived is stored.
- **All times come from the clock of the target.** Clocks of workers and callers do not matter.

### Loading now

For a load that should not wait, for example after the nightly batch of the ERP system has finished or after the cause of a failure has been fixed:

```sql
UPDATE _rowvioli.tables SET requested_at = now() WHERE source = 'erp';
```

`rowvioli run erp` does the same and then loads in its own process.

| Requested | Consequence |
|---|---|
| before a worker starts | one run, however often it was requested |
| while the table is loading | it loads once more afterwards, because the running read can be older than the request |
| while the table is loading, and that run fails | one more run at once, because the request was not served. Then the pause. |
| and the run that serves it fails | the normal retry with its pause takes over |

Nobody ever resets `requested_at`. The formula only compares two points in time, so there is no flag that a worker could clear while somebody sets it.

## A run

A run loads exactly one table, in a process of its own. It uses a single connection to the target, the control connection. On it the run holds the table lock, fills the staging table, checks, compares and publishes.

```mermaid
flowchart TD
    A["1 Claim<br/>take the table lock, count the attempt"] --> B["2 Read the table's row, decrypt the connection<br/>hand it to the connector"]
    B --> C["3 Fill the staging table<br/>connector reads, COPY writes, chunk by chunk"]
    C --> D["4 Check<br/>schema, unique keys, zero rows"]
    D --> E["5 Compute the diff<br/>into a small table, check the share of deletions"]
    E --> F["6 Publish<br/>one transaction: change log, mirror, loaded_at"]
    F --> G["7 Close the connection<br/>lock released, staging table gone"]

    B -.->|connector missing or connection broken| X["run failed<br/>target table unchanged, retried after the pause"]
    C -.->|source drops out| X
    D -.->|check violated| X
    E -.->|too many deletions| X
    F -.->|SQL error, rollback| X
```

Until the COMMIT in step 6, consumers see the old state. Any abort before that leaves the target table unchanged.

Three things hang on the control connection inside Postgres: the table lock, the TEMP tables and the open transaction. If the process dies in the middle of a step, Postgres removes all three. Nothing has to be cleaned up, and the run shows as dead until the retry.

### How the program works

Heavily simplified:

```python
def work(slots):                                   # the whole server
    while not sigterm_received():
        if a_slot_is_free() and something_is_claimable():   # due, within parallel and max_running
            start_process(load)                    # one process per table
        else:
            sleep(2)
    wait_for_running_processes()                   # each still ends after max_seconds

def load(target):                                  # target = control connection
    table = target.claim()                         # most overdue table: lock taken, attempt counted
    if table is None: return                       # another worker was faster

    read   = connectors[table.type].read           # the only thing a worker brings along
    chunks = read(decrypt(table.connection), table.name, table.options)
    target.copy_into_staging(chunks)               # writes chunk by chunk

    target.sql("check schema, keys, zero rows")
    target.sql("compute the diff into a small table, check the share of deletions")

    target.begin()
    target.sql("diff into the change log")
    target.sql("apply diff to the mirror")
    target.sql("loaded_at = now, attempts = 0")
    target.commit()                                # visible from here on
    target.close()                                 # lock released
```

Data passes through the program only in the lines `read` and `copy_into_staging`. Everything else is SQL sent to the target. The program never learns which rows changed, only how many.

`rowvioli run` is the same loop that ends when nothing is due any more.

### Checks before publishing

| Check | Aborts if |
|---|---|
| Schema | a column is missing or has changed its type, as far as the driver tells types apart (see [Types](#types)). A new column is added to the target. |
| Key | a key combination occurs twice in the staging table, a key column is null, or the key in the definition differs from the primary key of the mirror. |
| Safety limits | the source delivers zero rows, or more than `max_delete_share` of the rows would disappear. |

The share of deletions is known only from the diff, so it is checked after step 5. The safety limits keep a broken source from emptying the mirror in a perfectly consistent way.

A changed key is never converted. A person drops or renames the old mirror, and the next run builds it anew.

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
INSERT INTO raw_erp.customers__log SELECT :run, d.* FROM diff d;            -- unless log = false
DELETE FROM raw_erp.customers m USING diff d
 WHERE d._op IN ('D','U') AND d.customer_no = m.customer_no;
INSERT INTO raw_erp.customers SELECT customer_no, name, city FROM diff WHERE _op IN ('I','U');
UPDATE _rowvioli.tables SET loaded_at = now(), attempts = 0 WHERE id = :table;
UPDATE _rowvioli.runs SET status = 'ok', finished_at = now(), inserted = ..., updated = ..., deleted = ...
 WHERE run = :run;
COMMIT;
```

## Target schema

Per target table:

```
raw_erp.customers          mirror: columns of the source, primary key = key
raw_erp.customers__log     change log, unless log = false
  _run, _op                run and I, U or D
  ... all columns
```

Staging table and diff are TEMP tables on the control connection. They have no fixed name in the target and disappear with the connection.

Bookkeeping in the schema `_rowvioli`:

```
sources   id, name, type, target_schema, parallel, options, connection (ciphertext), key_id, enabled
tables    id, source, source_table, target_table, key, max_age, log, max_delete_share, max_seconds, options, enabled,
          loaded_at, attempted_at, attempts, requested_at, reason
runs      run, table, worker, started_at, finished_at, status,
          rows_read, inserted, updated, deleted, reason, definition
status    view over tables: age, due_at and status, computed on every query
meta      schema_version, max_running, definition (hash of the definition last applied)
```

- `sources` and the first line of `tables` are the definition. Only `apply` writes them. A table row carries the settings a table may override, with the source's filled in.
- The second line of `tables` is what the workers experienced, plus `requested_at`.
- `runs` is a log: one row per run. Nothing reads it to decide anything.
- `status` is what people look at. It shows a table as `new`, `loading`, `ok` or `failed`, with the `reason` of a failure in a column of its own. A table whose run died shows as `failed` with the reason `worker lost`.
- Progress can be computed there too, for example `loading, 485,000 of about 1,000,000 rows`. The holder of the table lock is in `pg_locks`, its rows so far are in Postgres' own `pg_stat_progress_copy`, and the expected number is the row count of the last run. A worker writes nothing for it.

Today's state is read from the mirror. What changed when is in the change log. Validity periods can be computed from it as a view.

Example: customer 7 moves between run 41 and 42, customer 9 is deleted.

```
mirror  raw_erp.customers        change log  raw_erp.customers__log
id | city                        _run | _op | id | city
 7 | Cologne                       40 | I   | 7  | Bonn
                                   40 | I   | 9  | Essen
                                   42 | U   | 7  | Cologne
                                   42 | D   | 9  | Essen
```

## Workers

A worker is stateless. It brings three things: its connectors, the address of the target and a key to decrypt connections. Everything else comes from the target. Scaling means starting another worker, and a crash loses nothing because nothing was kept in the worker.

```mermaid
sequenceDiagram
    participant P as Target Postgres
    participant A as Worker A
    participant B as Worker B
    participant C as Worker C

    Note over P: customers, orders, order_lines and suppliers are due
    par
        A->>P: customers: claim, load, COMMIT
    and
        B->>P: orders: claim, load, COMMIT
    and
        C->>P: order_lines: claim, load, COMMIT
    end
    B->>P: suppliers: claim
    Note over B: worker B drops out
    Note over P: lock released, run counts as dead
    Note over P: one minute later suppliers is due again
    C->>P: suppliers: claim, load, COMMIT
```

If one table fails or dies, the others are published all the same. The price of this independence: for a short time `orders` can already be new while `customers` is still old.

### States of a table

```mermaid
stateDiagram-v2
    [*] --> due: apply creates the row
    due --> loading: a worker claims it
    loading --> fresh: published
    loading --> pausing: failed or worker lost
    fresh --> due: older than max_age, or requested
    pausing --> due: pause is over, or requested
```

None of these states is stored. They follow from the facts in the row and from the locks that are held at this moment.

### Rules

- **One process per run.** The worker starts a process for every table it loads. A hanging run is ended after `max_seconds`, and a crashing driver takes only its own table with it.
- **Three limits.** `--slots` limits what one machine loads at the same time. `parallel` limits what a source has to bear. `max_running` in `_rowvioli.meta` limits what the target has to bear. The last two are counted in the target, across all workers.
- **Connections to the target.** One per running table, plus one per worker with which it asks whether something is claimable: due, and within `parallel` and `max_running`.
- **All workers on one target are equipped alike.** A worker takes any due table. If its connector is missing or the connection cannot be decrypted, the run fails with a reason that names the worker, for example `connector "sap" is not installed on worker etl-02`. Providing the connectors is the operator's task.
- **The definition is read when a table starts.** A change made by `apply` never interrupts a running load.

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

The prototype claimed this way with 6 workers of 4 slots, two sources with `parallel` 2 and 3, and `max_running = 4`. A probe every 20 ms never saw more than the limits, and both were reached. With the counting lock removed, the same test broke the total limit in 1 of 4 runs. Details in [docs/measurements.md](docs/measurements.md#9-the-prototype).

## Failures

| What happens | Consequence | Lock released after |
|---|---|---|
| Worker crashes while Postgres waits for it | transaction discarded, run dead, retried after the pause | under 0.3 s (measured) |
| Worker crashes while Postgres is computing a statement or waiting for a lock | as above, as soon as Postgres notices the loss | under 4 s with a connection check every 2 s (measured), otherwise when the statement ends |
| Machine or network drops out | as above, detected through TCP keepalive | about 60 s (not measured) |
| Source is unreachable for a moment | the run fails, the next one starts a minute later | right after |
| Source stops answering | the worker ends the run's process after `max_seconds` | right after |
| A table fails again and again | the pause doubles up to `max_age`. The status shows the reason and the number of attempts. | |
| A connector is not installed on a worker | the run fails with a reason that names the worker | right after |
| The target fails over to another node | connections drop, running loads end without publishing, the retry catches up | with the connection |
| Target Postgres is unreachable | workers wait and retry. Nothing is loaded. | |

In no case does anything half-done become visible: a COMMIT needs a command from the worker, and the worker is gone by then.

The program sets on its own connections:

- Keepalive: `keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=3`, `tcp_user_timeout=60000`
- `client_connection_check_interval = 2s`, so that Postgres looks for the client during a long statement too
- `lock_timeout` for adding a column, so that a long-reading consumer cannot block the run forever

The control connection must go to Postgres directly, not through a connection pooler in transaction mode.

## Connections

A connection is everything a connector needs to reach its source: address, user, password or token. It is written as a block in the definition. Secrets appear in it only as placeholders.

```toml
[erp.connection]
string = "Driver={ODBC Driver 18 for SQL Server};Server=sqlsrv01;Database=erp;UID=reader;PWD=$ERP_PASSWORD"

[weather.connection]
url   = "https://api.example.org"
token = "$WEATHER_TOKEN"
```

```mermaid
flowchart LR
    D["definition<br/>connection block with placeholders"] --> A[rowvioli apply]
    E["environment at deploy time<br/>ERP_PASSWORD=…"] --> A
    P["worker.pub<br/>next to the definition"] -.-> A
    A -->|"one ciphertext per source"| S[("_rowvioli.sources")]
    S -->|"read at the start of a run"| W[Worker]
    K["worker.key<br/>file on the worker"] -.->|"decrypts in memory"| W
    W -->|"hands the block to the connector"| Q[(Source)]
```

- **A person** writes the block and makes sure the variables are set when `apply` runs. A secret manager holds plain values such as a token or a password. Nobody builds a connection string by hand in a variable, and nobody percent-encodes a value by hand.
- **`apply`** fills in the placeholders, encrypts the block as a whole with the public key and stores one ciphertext per source. It aborts if a variable is missing.
- **The connector** receives the decrypted block as a dict. Which fields it expects is part of its documentation: `url` for `postgres`, `string` for `odbc`, `url` and `token` for `rest`, `path` for `file`.

The address of a source is visible in the definition and in its review, and still encrypted in the target. Someone who can only write to the target cannot point a password at another server. If the source is a cluster, that is part of the connection string and nothing rowvioli has to know.

For test and production with different addresses, the address becomes a placeholder too, for example `url = "$WEATHER_URL"`.

### How it is encrypted

- **A standard construction, not a home-made one.** Connections are encrypted as libsodium sealed boxes through PyNaCl: an X25519 key exchange with a one-time key, then authenticated encryption with XSalsa20-Poly1305. GitHub uses the same construction for repository secrets set through its API.
- **Tampering is detected.** A single flipped bit makes decryption fail.
- **Swapping is detected.** The name of the source is encrypted together with its connection. A ciphertext copied to another source is rejected.
- **Equal values look different.** Encrypting the same connection twice gives two different ciphertexts. `apply` therefore writes a new ciphertext every time, with the same content.

All four were tried out in [experiments/07_geheimnisse.py](experiments/07_geheimnisse.py), with a single value in place of a block.

### Where the keys live

There is one key pair for all workers of a target.

| Key | Where | Who may see it |
|---|---|---|
| Public key | `worker.pub`, a file next to the definition | everybody. It changes only through a merge request. |
| Private key | a file on each worker, named by `ROWVIOLI_KEY_FILE`, mode 600 | the service user of the worker |

- The private key is never in the database, never in Git, and never passed as the value of an environment variable.
- The public key is taken from the file next to the definition, not from the database. Someone with write access to the database therefore cannot slip in a key of their own.
- A worker can hold several private keys, which is what makes rotation possible.

### What happens to the decrypted connection

- It exists only in the memory of the run's process and of the connector.
- It is never written to `_rowvioli.runs`, to the answer on stdout or to a log.
- Database drivers like to quote the connection string in error messages, and parts of a value they cannot parse. The program removes the values of the connection from every error text before it stores or prints it. A password in a URL is the case where a driver quotes a part: `apply` percent-encodes a value that lands in the user info (`scheme://user:$PASSWORD@host`), so the driver never misparses it.

### Rotation and loss

A new password: change the variable and run `apply` again.

A new key pair:

1. `rowvioli key new` creates a new pair.
2. The new private key is added to every worker, next to the old one.
3. The new public key replaces `worker.pub`. `apply` encrypts every connection anew.
4. The old private key is removed.

If the private key is lost, a new pair and one `apply` restore everything, because the definition and the environment still hold all values.

### What this protects against, and what not

| Situation | Protected |
|---|---|
| Someone reads the database, a backup or a replica | yes, they see ciphertext only |
| Someone with write access changes or swaps a ciphertext | yes, decryption fails |
| Someone with write access changes a definition to redirect a connection | yes for the shipped connectors, the address is inside the ciphertext |
| A worker is compromised | **no**. It holds the private key and a database connection and can read every connection. |
| The place where `apply` runs is compromised | **no**. It holds every secret in its environment. |
| Someone with write access puts back an older ciphertext of the same source | **no** |

The encryption will not be the weak point. The private key file and the deployment environment are. Two measures limit the damage: accounts in the source systems that may only read, and as few people as possible who can log in to a worker or change the deployment.

A connector is code the operator trusts. It receives the decrypted connection and can do with it what it wants. The promise above holds for the shipped connectors.

## Commands

| Command | Does | Needs |
|---|---|---|
| `rowvioli init` | Creates the schema `_rowvioli` in the target. | target |
| `rowvioli key new` | Creates a key pair in the current directory: `worker.key` for the workers and `worker.pub` for the definition. Overwrites neither. | nothing |
| `rowvioli list erp` | Prints the tables of a source with their keys, ready to paste into the definition. | definition, environment, connector, source |
| `rowvioli apply --check sources/` | Reads the definition and checks it. Writes nothing. Meant for a laptop and for the pipeline of a merge request. | definition |
| `rowvioli apply sources/` | Writes the definition into the target: one row per source and table, connections encrypted. | definition, environment, `worker.pub` (or `--key <file>`), target |
| `rowvioli work --slots 4` | Runs permanently and loads whatever is due, up to four tables at a time. | connectors, private key, target |
| `rowvioli run` | Loads everything that is due, once, and ends. | connectors, private key, target |
| `rowvioli run erp` | Requests all tables of `erp` and loads until nothing of `erp` is due. | connectors, private key, target |
| `rowvioli run erp dbo.Customers` | The same for a single table, named as in the source. An unknown or disabled name fails. | connectors, private key, target |

Naming something means "this, now". `run` without a name means "whatever is due". `run` takes `--slots` too.

Every command that needs the target finds it in `ROWVIOLI_TARGET_URL`. A worker finds its private key through `ROWVIOLI_KEY_FILE`. `run` and `work` check both at start and name the one that is missing.

`apply` in detail:

- **Idempotent.** Applying the same definition twice gives the same state. Sources and tables are created or updated by name.
- **It never touches what the workers experienced.** `loaded_at`, `attempted_at`, `attempts` and `requested_at` stay as they are. A deployment triggers no load and loses no request. A table that is new in the definition has never been attempted and is therefore due at once.
- **The definition is always the whole.** `apply` gets a directory. What is no longer in it is disabled, never deleted, and its target table stays. Applying the wrong directory by mistake is undone by applying the right one.
- **Disabling is the only way to stop a table.** Until then it is loaded and retried. A run that is loading the table when it is disabled finishes.
- **It fails rather than guess.** On a missing variable, two tables with the same target table, two sources with the same `target_schema`, or a target without the schema `_rowvioli` (then it says: run `rowvioli init` first).
- **One transaction.** If anything fails, nothing changes.

Answer of `run` on stdout:

```json
{"seconds": 41.2,
 "tables": {
  "raw_erp.customers": {"status": "ok", "inserted": 12, "updated": 3, "deleted": 1},
  "raw_erp.suppliers": {"status": "failed", "reason": "62 % of the rows would be deleted"}}}
```

| Exit code | Meaning |
|---|---|
| 0 | No table failed. |
| 1 | At least one table failed. The other tables are published. |

## Operation

The same command at every size:

| Size | What runs | What is added |
|---|---|---|
| One machine, no service | cron starts `rowvioli run` every minute | nothing |
| One worker as a service | `rowvioli work --slots 4` | a service to supervise |
| Several workers | the same on more machines | nothing else changes |

### The definition

```
etl-definition/
  sources/
    erp.toml
    crm.toml
    weather.toml
  worker.pub         public key for encrypting connections
  pyproject.toml     names the program as a dependency, for apply
  uv.lock            pins its version
```

[examples/definition](examples/definition) is a template, with a GitLab pipeline.

- A merge request is the only way to change a source. Its pipeline runs `rowvioli apply --check sources/`.
- The pipeline runs `rowvioli apply sources/` after the merge. The organisation's secret manager injects the secrets as environment variables.
- The pipeline needs access to the target. It needs no driver and no route to any source.
- Every run records a hash of the definition it ran with.

### A worker

To be set up once: the program with its connectors, for example `uv tool install "rowvioli[file]"`, and the drivers they need.

```
/etc/rowvioli/env          ROWVIOLI_TARGET_URL and ROWVIOLI_KEY_FILE
/etc/rowvioli/worker.key   the private key, readable only by the service user
```

```ini
# systemd service for a worker
[Service]
User=etl
EnvironmentFile=/etc/rowvioli/env
ExecStart=rowvioli work --slots 4
Restart=always
TimeoutStopSec=3600   # as long as max_seconds, so running tables can finish
KillMode=mixed        # SIGTERM to the worker only, so its run processes are not ended with it
```

- A worker has no checkout and no file that describes a source. A new source needs no change on any worker.
- Source passwords are not on the worker. They are inside the encrypted connections in the target and are decrypted when a run starts.
- Test and production are separate targets with their own workers, their own key pair and the same definition.
- Whoever runs containers can build an image from the program and the drivers, starting from [examples/Dockerfile](examples/Dockerfile). It is not required.

### The target

The target is exactly one database. Mirrors and bookkeeping have to be in the same database, because both are published in one transaction.

- **A cluster with failover.** The address names all nodes and the worker connects to the one that accepts writes.
- **Several target databases.** Each gets its own workers and its own definition.
- **Consumers on replicas** see only published states.
- **A connection pooler** in front of the target works in session mode only.

Rights in the target:

| Who | Needs |
|---|---|
| The pipeline that runs `apply` | to write the definition |
| The workers | to read the definition, to write what they experienced, to create and write the mirrors |
| Whoever may request a load, for example a web UI | to read the status view, to write `requested_at` and nothing else |
| Consumers | to read the mirrors |

The program creates no roles. Whoever can write the definition decides what is loaded, so that right belongs to the pipeline alone. A small set-up can use one user for everything.

### Deploying while loads are running

| Change | Running tables | Takes effect from |
|---|---|---|
| Changed definition | keep running untouched | the next table a worker starts |
| New source or table | keep running untouched | at once. It has never been attempted and is therefore due. |
| New password | keep running untouched | the next table of that source |
| New connector | keep running untouched | when it is installed on every worker. Install first, then apply the source that uses it. |
| New program version | run to completion, each within `max_seconds` | the restart of the worker. On SIGTERM it starts nothing new, waits for its runs and exits. |

A worker that is killed hard takes its runs with it. They show as `worker lost` and are retried after the pause.

## Connectors

The whole contract is one function:

```python
def read(connection: dict, table: str, options: dict) -> Iterator[pyarrow.RecordBatch]:
    """Yield the rows of one table, chunk by chunk."""
```

| Goes in | Meaning | From |
|---|---|---|
| `connection` | where the source is and how to get in | the decrypted connection of the source |
| `table` | what to read there | the name in the definition |
| `options` | how to read, for example a separator or a page size | the definition, nothing secret |

Out come Arrow batches with a schema that stays the same, and nothing else. A connector never sees the target, a lock or another table. It has to keep two promises: deliver in chunks instead of all at once, and keep column types stable.

A connector may offer a second function, `tables(connection)`, that lists the tables of the source with their keys. Only `rowvioli list` uses it. A worker never calls it.

| Connector | Covers | Built on | Needed on the worker |
|---|---|---|---|
| `postgres` | PostgreSQL | ADBC | nothing |
| `odbc` | MSSQL, Informix, any ODBC source | arrow-odbc | the vendor's ODBC driver |
| `file` | CSV, Excel, Parquet, JSON files | DuckDB | access to the files |
| `rest` | flat JSON objects over HTTP, page by page | Python generator | nothing |

Version 0.1 ships `postgres` and `file` (without JSON). `odbc` and `rest` come with 0.2.

### Two ways to get a connector

| Way | Set-up | In the definition | Meant for |
|---|---|---|---|
| Shipped | `pip install rowvioli[odbc]` | `type = "odbc"` | The connectors in the table above. The core stays small, heavy dependencies come only on request. |
| Separate package | `pip install rowvioli-weather` | `type = "weather"` | Everything else. The package registers through an entry point. |

Installing connectors on the workers is the operator's task.

### A custom connector, complete

```python
# rowvioli_weather.py
import httpx
import pyarrow as pa

SCHEMA = pa.schema([("station", pa.string()),
                    ("time", pa.timestamp("s", tz="UTC")),
                    ("temp", pa.float64())])

def read(connection, table, options):
    auth, page = {"Authorization": "Bearer " + connection["token"]}, 1
    while rows := httpx.get(connection["url"] + options["path"], params={"page": page}, headers=auth).json():
        yield pa.RecordBatch.from_pylist(rows, schema=SCHEMA)
        page += 1
```

```toml
# pyproject.toml of the connector package
[project.entry-points."rowvioli.connectors"]
weather = "rowvioli_weather"
```

```toml
# sources/weather.toml
[weather]
type    = "weather"
max_age = "1h"

[weather.connection]
url   = "https://api.example.org"
token = "$WEATHER_TOKEN"

[weather.tables]
readings = { key = ["station", "time"], path = "/v1/readings" }
```

The shipped `rest` connector does the same without code for the simple case. The columns are then named in the definition:

```toml
[weather.tables.readings]
key     = ["station", "time"]
path    = "/v1/readings"
columns = { station = "text", time = "timestamptz", temp = "float8" }
```

### Types

The column types in the target follow from the Arrow schema the connector delivers.

- **Arrow only.** A connector names its schema. Types are never guessed from the first rows, so they cannot flip between two runs.
- **Files.** The `file` connector delivers every CSV and Excel column as text, except those the option `columns` names with a DuckDB type, for example `columns = { amount = "decimal(10,2)" }`. Parquet keeps its own types.
- **Decimals from Postgres.** The ADBC driver reads `numeric` as text and cannot write text into a `numeric` column. The `postgres` connector therefore has to convert to `decimal128`. This was investigated in `data-extractor` (ADR-0014 there). An unconstrained `numeric` with more than 38 digits on either side of the point fails the run.
- **The driver decides the types in the target.** ADBC creates the staging table and the mirror takes its types. Some are lost on the way: `varchar(n)` arrives as `text`, `numeric(p,s)` as `numeric`. The schema check sees types only as the driver shows them, so a change from `text` to `varchar(20)` passes unseen. This is the price of one driver (decision 28).

## Web UI

Everything a UI needs is in the target. It is a small application of its own with database access to `_rowvioli` and not part of the program.

| The UI should | From where | Possible |
|---|---|---|
| Show all tables with age, status and failure reason | `_rowvioli.status` | yes |
| Show when a table is due next | `_rowvioli.status` | yes |
| Tell loading, failed and dead apart | `_rowvioli.status` | yes. A dead run shows as `failed` with the reason `worker lost`. |
| Show past runs with duration and counts | `_rowvioli.runs` | yes |
| Show which rows a run changed | change log of the table | yes, unless `log = false` |
| Show which definition a run used | `runs.definition` | yes, as a hash |
| Load a table now | `requested_at` in `_rowvioli.tables` | yes |
| Show the progress of a running run | `_rowvioli.status` | yes, while the staging table is filled. Not built, and not tried with a role without special rights. |
| Cancel a run | Postgres terminates the run's control connection | only for the moment: the retry starts it again after a minute |
| Stop a table for good | | no. It is removed from the definition, and `apply` disables it. |
| Change a source or its password | | no. That is the definition, and it changes through `apply`. |
| Show complete log lines | the worker's log system | not from the target |

## Measurements

Short version. Set-up, all numbers and limitations are in [docs/measurements.md](docs/measurements.md). `uv run bench/bench.py` measures the same cases at 10⁶ rows through the program.

| Case | 10⁶ rows | 10⁷ rows |
|---|---|---|
| Comparison when nothing changed | 0.5 s | 13 s |
| Computing the diff at 1 % changes | not measured | 39 s |
| Publishing at 1 % changes | not measured | 17 s |
| Compare and publish in one transaction (earlier variant) | 1.9 s | 59 s |
| Without a key: replace everything | 2.9 s | 40 s |
| Filling the staging table from a client through ADBC | 0.5 s | not measured |

A table with 900 columns and 100,000 rows takes 5.7 s to compare. In the prototype a run process cost about 0.2 s before its claim, and the claim itself 4 ms at 1000 tables.

In the intended working range of up to 10⁶ rows a table costs a few seconds. At 10⁷ this path is slower than `hpdl` (25 to 42 s there for the whole run including reading) and in exchange does without hashes, key ranges and partitions.

## Further documents

| File | Content |
|---|---|
| [GLOSSARY.md](GLOSSARY.md) | Terms |
| [docs/decisions.md](docs/decisions.md) | Every decision with its reason, its price and the rejected alternative |
| [docs/measurements.md](docs/measurements.md) | All measurements with set-up and limitations |
| [docs/package.md](docs/package.md) | Proposal for the package, the first version and the repo layout |
| [docs/open-points.md](docs/open-points.md) | What is undecided, unverified or unbuilt |
| [experiments/](experiments/README.md) | The scripts behind the measurements |

Sketches from the first discussion (private pages, in German). They show the earlier model with orders, a jobs repo on every load host and an external scheduler, and the command and schema are still called `etl` and `_etl` there:

- [The whole picture as a page with drawings](https://claude.ai/artifact/EgxJYvAXjTfhUVYVWe4vEh)
- [Integration in a company](https://claude.ai/artifact/TpvxQYyxDKMhwY9EXgq2Ma)
- [Flow and integration](https://claude.ai/artifact/VadCBs9SdqrodwTDqSPkSN) (with exit code 75)
- [One way into the target](https://claude.ai/artifact/YWwdsQGGbop5sYkk5sMqNg) (with one shared transaction)
- [Path of the job data](https://claude.ai/artifact/4jdjm3LEJpKWDfXCjUDqGb) (with one file per table)
