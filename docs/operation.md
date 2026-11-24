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
[Unit]
StartLimitIntervalSec=0

[Service]
User=etl
EnvironmentFile=/etc/rowvioli/env
ExecStart=/home/etl/.local/bin/rowvioli work --slots 4
Restart=always
RestartSec=5
# as long as max_seconds, so running tables can finish
TimeoutStopSec=3600
# SIGTERM to the worker only, so its run processes are not ended with it
KillMode=mixed
```

`ExecStart` needs the program's absolute path: `uv tool install` puts it into `~/.local/bin` of the user who installed it (`command -v rowvioli` shows where). `RestartSec` and `StartLimitIntervalSec=0`, which belongs under `[Unit]`, where systemd reads it, are there because a worker started while the target is down exits with 1 at once (`Failed to connect: ...`, so a wrong address is seen at the first start); only a worker that has connected once retries every two seconds. Without them systemd restarts it five times within a second and then leaves the service failed, which a target that comes up a minute later does not undo.

- **A worker says what it does**, one line per event on stderr, the same line wherever stderr goes: local date and time, a mark (`▶` started, `✔` ok, `✘` failed, `⚠` the target is unreachable), then the text. A run's line has columns: the target table, `started`, `ok` or `failed`, the seconds since its claim, then the counts (`+inserted ~updated -deleted`) or the reason. `run` writes the start and end lines of its runs, not the worker's start line. A worker with nothing to do writes no line, and `rowvioli status` shows what is due when. Nothing is stored and nothing is configured: the lines are for a person at a terminal and for the log system you already have (journald, Docker), and what happened to a table stays in `_rowvioli.runs`. At a terminal the worker first shows its mascot.

  ```
  2026-11-12 14:03:00   worker mac:4711 started with 4 slots on dwh
  2026-11-12 14:03:01 ▶ raw_shop.orders              started           run 17
  2026-11-12 14:03:01 ✔ raw_shop.orders              ok          0.4s  +0 ~3 -10
  2026-11-12 14:03:03 ▶ raw_crm.contacts             started           run 18
  2026-11-12 14:03:05 ✘ raw_crm.contacts             failed      2.1s  62 % of the rows would be deleted, more than max_delete_share = 0.5 allows: the source table may have been replaced or emptied; if so, max_delete_share = 1.0 on the table lets one run through
  2026-11-12 14:05:40 ⚠ the target is unreachable, connecting again every two seconds: …
  2026-11-12 14:05:52 ✔ the target is reachable again after 12s
  2026-11-12 14:09:12   stopping, 1 run finishes
  ```

  The lines are coloured, in a pipe, a file and a container log too: the time dim, a `✔` line green, a `✘` line red, a `⚠` line yellow. `NO_COLOR=1` (any non-empty value, `NO_COLOR=0` too) or `TERM=dumb` switches the colour off and leaves the lines as they are. Under cron, the mail or log file gets the colour codes unless `NO_COLOR` is set. A worker whose stderr is the systemd journal, as it is for a service by default, writes no colour: `journalctl` strips escape codes in its usual view, but the journal keeps them, and `journalctl -o json` hands such a message to a log shipper as an array of bytes. The legacy Windows console prints the escape codes as text; set `NO_COLOR=1` there.

  Control characters in a table name or a reason are written as `?`; `rowvioli status` and the error messages of `list` and of a refused target do the same. What is stored and what is JSON stays as it is.

  Output never stops a worker or changes the exit code of `run`. A line that cannot be written, to a pipe whose reader is gone, a full disk or a log stream that stalls, is lost, and the next line is tried again, so a worker speaks again once the failure passes.

  A failure carries the reason of the status view; `worker lost` and `ended after max_seconds` are failures too. `the target is unreachable` is written once per outage, and `the target is reachable again after <seconds>s` once when it ends, so a log shows how long it lasted. `run` has neither line: it fails on an unreachable target. Run processes keep their stderr discarded, so no driver message from a source can carry a connection value into a log, and what a library writes to their stdout is dropped too. The line for an unreachable target keeps the driver's message as one line, like a reason, with the password of `ROWVIOLI_TARGET_URL` replaced by `***`.
- **`rowvioli status` shows what is**, without `psql`. It prints the status view as a table; the `due` column says `now` or `in 20m`, so `ok` with an age above the maximum age is a table that is due and that nobody has taken yet (no worker runs). It computes nothing the view does not.
- A worker has no checkout and no file that describes a source. A new source needs no change on any worker. `rowvioli list` run on a worker's machine, where there is no `sources/`, reads the source from the target with the worker's key.
- Source passwords are not on the worker. They are inside the encrypted connections in the target and are decrypted when a run starts.
- Test and production are separate targets with their own workers, their own key pair and the same definition.
- Whoever runs containers can build an image from the program and the drivers, starting from [examples/Dockerfile](../examples/Dockerfile). It is not required. Its log gets the coloured lines, which `docker logs` shows as colour; for a log collector that does not render them, set `NO_COLOR=1`. Give the container a restart policy (`restart: always` in Compose, `docker run --restart unless-stopped`) and never one that gives up after a few tries: a worker that starts before its target exits at once, as for the unit above, and must be started again until the target is there.

## The target

The target is exactly one database. Mirrors and bookkeeping have to be in the same database, because both are published in one transaction.

- **A cluster with failover.** The address names all nodes and asks for the one that accepts writes: `postgresql://etl@pg01,pg02/dwh?target_session_attrs=read-write`. Without `target_session_attrs` libpq takes the first node that answers, a standby too.
- **Several target databases.** Each gets its own workers and its own definition.
- **Consumers on replicas** see only published states.
- **A connection pooler** in front of the target works in session mode only. One in transaction mode is refused at the start of every command, before anything is claimed ([Failures](target.md#failures)).

Rights in the target:

| Who | Needs |
|---|---|
| The pipeline that runs `apply` | to write the definition |
| The workers | to read the definition (`rowvioli list` run there without `sources/` reads `_rowvioli.sources` and `_rowvioli.meta` with the worker's role), to write what they experienced, to create and write the mirrors, and to write the record of the columns: `SELECT, INSERT, UPDATE, DELETE` on `_rowvioli.columns` and `SELECT, INSERT` on `_rowvioli.columns__log`. Without these every publish fails with `permission denied for table columns: the worker's role lacks a right on _rowvioli.columns, which rowvioli init printed with the upgrade to version 4 (docs/operation.md "The target")` (or `columns__log`). |
| Whoever may request a load, for example an application of your own | to read the status view, to write `requested_at` and nothing else; to see progress, membership in `pg_read_all_stats` |
| Consumers | to read the mirrors and, for history, the views `<target table>__history`. A view is a plain view and runs with its owner's rights, so the right to read it is enough; the change log needs none. Default privileges on tables cover views. A grant on a history view given by name stays when a run builds the view anew ([Target schema](target.md#target-schema)). To tell a quiet source from a worker that is gone, `USAGE` on `_rowvioli` and `SELECT` on `_rowvioli.status`: that gives the view and nothing else in the schema (`tables`, `runs` and the connections stay closed). |
| Auditors, and consumers who want to know which columns a table had | `USAGE` on `_rowvioli` and `SELECT` on the view `_rowvioli.columns__history`, and nothing else: the view is a plain view and runs with its owner's rights, so `columns` and `columns__log` stay closed. The view shows the columns of every table of the target, in every schema, and its notes name indexes, constraints and roles with grants: give it to whom may know them. |

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
GRANT SELECT, INSERT, UPDATE, DELETE ON _rowvioli.columns TO worker;     -- from version 4, which `rowvioli init` prints
GRANT SELECT, INSERT ON _rowvioli.columns__log TO worker;
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
GRANT USAGE ON SCHEMA _rowvioli TO consumer;                -- optional: to read the status; without it a stopped mirror looks like a quiet source
GRANT SELECT ON _rowvioli.status TO consumer;
GRANT SELECT ON _rowvioli.columns__history TO consumer;     -- optional: which columns a table had at a moment
```

A worker needs `CREATE` on the database only to create the schemas of the target tables. With the schemas created beforehand, `GRANT ALL ON SCHEMA raw_erp TO worker` replaces it. Default privileges apply to objects the role named in `FOR ROLE` creates, so name the worker's role there.

**All workers of a target run the same drivers.** The types a table gets follow what the driver delivers, so they would depend on the worker that loads it. A run that changes columns under another version of the program or of the driver than the table's last successful run had records the changes `by = reader`, with both versions ([The columns table](target.md#the-columns-table)); it does not stop.

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

Ctrl+C (SIGINT) is the opposite of SIGTERM, for `work` and for `run`: nothing waits. The run processes have a process group of their own, so at a terminal only the worker gets the signal (on Windows a run gets it too and may record it as its reason). It ends its run processes, writes one line, `stopped by Ctrl+C, 2 runs ended` (`1 run ended` for one), and exits with 130, without a traceback. It notices the signal within two seconds, except while it connects again to an unreachable target: then once that attempt gives up. A Ctrl+C that lands in the instant the worker asks the target cancels that query only: `work` writes `the target is unreachable` with `canceling statement due to user request` and goes on, `run` ends with that message and exit code 1; press it again. Nothing is recorded: the tables of the ended runs close as `worker lost`, as after a hard kill, and are retried after the pause. `run <source>` interrupted while it requests its tables, before its loop starts, still ends with Python's traceback, or with `canceling statement due to user request` and exit code 1. Ctrl+Z stops the worker alone: its runs go on, and it hears of them after `fg`.

**From version 3 of `_rowvioli` (0.4.1 and before) to 4.** Version 4 adds the columns table with its change log and history view, and the version of the program and of the driver to `runs`. Install the new version on the workers, then run `rowvioli init` once, as the role that owns `_rowvioli.runs`, which is the one that ran the first `init`, or as a superuser: the step alters that table, which Postgres allows only its owner, and creates tables in `_rowvioli`. Rights granted to another role are not enough: `init` then fails and changes nothing. It brings the target to version 4, changes nothing else, and prints the two `GRANT` statements above, with `worker` standing for the role of your workers; give them to that role, which the program never does:

```
the schema _rowvioli is brought from version 3 to 4; a worker's role needs these rights on its new objects, which the program does not grant (worker stands for that role):
GRANT SELECT, INSERT, UPDATE, DELETE ON _rowvioli.columns TO worker;
GRANT SELECT, INSERT ON _rowvioli.columns__log TO worker;
the schema _rowvioli is ready in the target
```

A worker of 0.4.1 refuses version 4 (`the target has schema version 4, this program works with version 3`) and every command of the new version but `init` and `status` refuses version 3 (`the target has schema version 3, this program works with version 4; rowvioli init brings it to 4`), so stop every old worker before `init` and start the new ones after the grants. An old worker forgotten through `init` damages nothing: each of its run processes refuses version 4 before it claims a table, and it writes `a run process ended with exit code 1 before it claimed anything` about a dozen times a second, without a pause, until it is stopped. A target that `init` builds new is of version 4 and prints nothing more than that it is ready. The first run after the upgrade records every table's columns as `found`, but what it changes, which it records by its cause (`reader`, since the version before recorded none) and notifies; a table that was stuck on a missing column or a changed type resolves by itself if it has a change log. A table that was stuck on a primary key other than the definition's resolves too: a primary key a person changed is put back, a key the definition changed is taken, and where nothing in the target tells which, the run says the statement that does ([A key](loading.md#columns)).

From 0.1.0, update every worker before applying new tables: a mirror that a new worker creates has `numeric(p,s)` where the source has it, and a worker of 0.1.0 fails on it with `has changed its type from numeric(10,2) to numeric`. Going back to 0.1.0 needs `ALTER TABLE ... ALTER <column> TYPE numeric` on such columns, in the mirror and its change log.

A worker that is killed hard takes its runs with it. They show as `worker lost` and are retried after the pause.
