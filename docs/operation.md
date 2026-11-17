# Operation

Running rowvioli: the definition's repository, a worker as a service and what it says, the target with its rights, and deploying while loads are running.

The same command at every size:

| Size | What runs | What is added |
|---|---|---|
| One machine, no service | cron starts `rowvioli run` every minute | nothing |
| One worker as a service | `rowvioli work --slots 4` | a service to supervise |
| Several workers | the same on more machines | nothing else changes |

## The definition

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

[examples/definition](../examples/definition) is a template, with a GitLab pipeline.

- A merge request is the only way to change a source. Its pipeline runs `rowvioli apply --check sources/`.
- The pipeline runs `rowvioli apply sources/` after the merge. The organisation's secret manager injects the secrets as environment variables.
- The pipeline needs access to the target. It needs no driver and no route to any source.
- Every run records a hash of the definition it ran with.

## A worker

To be set up once: the program with its connectors, for example `uv tool install "rowvioli[file,odbc,rest]"`, and the drivers they need.

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

- **A worker says what it does**, one line per event on stderr, each starting with local date and time. `run` writes the start and end lines of its runs, not the worker's start line. A worker with nothing to do is silent, and `rowvioli status` shows what is due when. Nothing is stored and nothing is configured: the lines are for a person at a terminal and for the log system you already have (journald, Docker), and what happened to a table stays in `_rowvioli.runs`. At a terminal the worker first shows its mascot; in a log there are only the lines.

  ```
  2026-11-12 14:03:00 worker mac:4711 started with 4 slots on dwh
  2026-11-12 14:03:01 raw_shop.orders started, run 17
  2026-11-12 14:03:01 raw_shop.orders ok after 0.4s: 0 inserted, 3 updated, 10 deleted
  2026-11-12 14:03:05 raw_crm.contacts failed after 2.1s: 62 % of the rows would be deleted
  2026-11-12 14:09:12 stopping, 1 run finishes
  ```

  A failure carries the reason of the status view; `worker lost` and `ended after max_seconds` are failures too. `the target is unreachable` is written once per outage. Run processes keep their stderr discarded, so no driver message from a source can carry a connection value into a log, and what a library writes to their stdout is dropped too. The line for an unreachable target keeps the driver's message, with the password of `ROWVIOLI_TARGET_URL` replaced by `***`.
- **`rowvioli status` shows what is**, without `psql`. It prints the status view as a table; the `due` column says `now` or `in 20m`, so `ok` with an age above the maximum age is a table that is due and that nobody has taken yet (no worker runs). It computes nothing the view does not.
- A worker has no checkout and no file that describes a source. A new source needs no change on any worker.
- Source passwords are not on the worker. They are inside the encrypted connections in the target and are decrypted when a run starts.
- Test and production are separate targets with their own workers, their own key pair and the same definition.
- Whoever runs containers can build an image from the program and the drivers, starting from [examples/Dockerfile](../examples/Dockerfile). It is not required.

## The target

The target is exactly one database. Mirrors and bookkeeping have to be in the same database, because both are published in one transaction.

- **A cluster with failover.** The address names all nodes and asks for the one that accepts writes: `postgresql://etl@pg01,pg02/dwh?target_session_attrs=read-write`. Without `target_session_attrs` libpq takes the first node that answers, a standby too.
- **Several target databases.** Each gets its own workers and its own definition.
- **Consumers on replicas** see only published states.
- **A connection pooler** in front of the target works in session mode only.

Rights in the target:

| Who | Needs |
|---|---|
| The pipeline that runs `apply` | to write the definition |
| The workers | to read the definition, to write what they experienced, to create and write the mirrors |
| Whoever may request a load, for example an application of your own | to read the status view, to write `requested_at` and nothing else; to see progress, membership in `pg_read_all_stats` |
| Consumers | to read the mirrors and, for history, the views `<target table>__history`. A view is a plain view and runs with its owner's rights, so the right to read it is enough; the change log needs none. Default privileges on tables cover views. |

The same as SQL, for the roles `pipeline`, `worker`, `requester` and `consumer` and a target database `dwh`. It was tried out with exactly these statements:

```sql
-- the pipeline that runs apply
GRANT USAGE ON SCHEMA _rowvioli TO pipeline;
GRANT SELECT, INSERT, UPDATE ON _rowvioli.sources, _rowvioli.tables, _rowvioli.meta TO pipeline;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA _rowvioli TO pipeline;

-- the workers
GRANT USAGE ON SCHEMA _rowvioli TO worker;
GRANT SELECT ON _rowvioli.sources, _rowvioli.tables, _rowvioli.meta, _rowvioli.status TO worker;
GRANT UPDATE ON _rowvioli.tables TO worker;
GRANT SELECT, INSERT, UPDATE ON _rowvioli.runs TO worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA _rowvioli TO worker;
GRANT CREATE ON DATABASE dwh TO worker;

-- whoever may request a load (add pg_read_all_stats for progress)
GRANT USAGE ON SCHEMA _rowvioli TO requester;
GRANT SELECT ON _rowvioli.status, _rowvioli.tables TO requester;
GRANT UPDATE (requested_at) ON _rowvioli.tables TO requester;

-- consumers: what the workers create from now on, and what exists
ALTER DEFAULT PRIVILEGES FOR ROLE worker GRANT USAGE ON SCHEMAS TO consumer;
ALTER DEFAULT PRIVILEGES FOR ROLE worker GRANT SELECT ON TABLES TO consumer;
GRANT USAGE ON SCHEMA raw_erp TO consumer;                  -- for a schema that exists already
GRANT SELECT ON ALL TABLES IN SCHEMA raw_erp TO consumer;   -- and its tables
```

A worker needs `CREATE` on the database only to create the schemas of the target tables. With the schemas created beforehand, `GRANT ALL ON SCHEMA raw_erp TO worker` replaces it. Default privileges apply to objects the role named in `FOR ROLE` creates, so name the worker's role there.

The program creates no roles. Whoever can write the definition decides what is loaded, so that right belongs to the pipeline alone. A small set-up can use one user for everything.

## Deploying while loads are running

| Change | Running tables | Takes effect from |
|---|---|---|
| Changed definition | keep running untouched | the next table a worker starts |
| New source or table | keep running untouched | at once. It has never been attempted and is therefore due. |
| New password | keep running untouched | the next table of that source |
| New connector | keep running untouched | when it is installed on every worker. Install first, then apply the source that uses it. |
| New program version | run to completion, each within `max_seconds` | the restart of the worker. On SIGTERM it starts nothing new, waits for its runs and exits. |

On Windows the stop signal is Ctrl+Break instead of SIGTERM.

A worker that is killed hard takes its runs with it. They show as `worker lost` and are retried after the pause.
