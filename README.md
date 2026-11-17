# rowvioli

<p align="center"><img src="https://raw.githubusercontent.com/romanhaendler/rowvioli/main/docs/mascot.svg" width="360" alt="Two identical ravioli mirroring each other and holding hands"></p>

> **Version 0.1.0, the first release.** What is proven and what is not is listed in [docs/measurements.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/measurements.md) and [docs/open-points.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/open-points.md).

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
export ROWVIOLI_TARGET_URL=postgresql://etl@pg01/dwh   # the target: the one variable every command needs
rowvioli key new            # once per target: worker.key for the workers, worker.pub next to the definition
rowvioli apply --init       # once per deployment: writes sources/ into the target, creating the schema first
rowvioli work               # on any number of machines, each with a copy of worker.key beside it: keeps every table fresh
rowvioli status             # whenever you want to look
```

```
$ rowvioli status
source  table             target             max_age  age     due        status   reason
crm     contacts          raw_crm.contacts   1d       3h      in 50s     failed   62 % of the rows would be deleted
erp     public.customers  raw_erp.customers  1h       1h 3m   now        loading  485,000 of about 1,000,000 rows
erp     public.items      raw_erp.items      1h       40m     in 20m     ok
erp     public.orders     raw_erp.orders     5m       2m 14s  in 2m 46s  ok
```

That is the whole usage. `docker compose up` in [examples/quickstart](https://github.com/romanhaendler/rowvioli/tree/main/examples/quickstart) plays it with a source and a target. There is no schedule, no queue and no job. One table in the target is work list, state and monitoring at once.

Two ideas carry the design:

- **You state the freshness.** A table is due when it is older than its `max_age`. A worker takes the table that misses its target the most. A table that has to be loaded at a time of day names that too: a load time is a request the clock makes.
- **Postgres does everything that is hard.** The connection of a run is its lock and its sign of life. Postgres compares the rows, counts what is running and computes what is due. The program passes rows from the source to the target and never holds a whole table in memory.

## Guarantees

- **Never a half-loaded or empty state.** For every table, consumers see the state before or after a run, nothing in between.
- **Never two runs on the same target table.** This holds across machines and workers.
- **Failed and dead runs are retried** without heartbeats or deadlines, after a pause that grows from one minute.
- **Bounded memory.** Per table, a worker holds only a few chunks of the size the connector delivers (about 16 MB with ADBC).
- **One flow for everything.** Initial load, follow-up load and tables without a key take the same path.

What it is not:

- Not a general scheduler. It knows how old a table may be and at which times of day it is due, and nothing else about time.
- Not a transformation tool. Columns arrive the way the source delivers them.
- Not a tool for targets other than PostgreSQL.

## Install

rowvioli is a command-line program for Python 3.11 or newer. The core reads from PostgreSQL; each other shipped connector is an extra, so its heavy dependency comes only on request:

```sh
uv tool install rowvioli                        # or: pip install rowvioli
uv tool install "rowvioli[file,odbc,rest]"      # with the extras: file, odbc, rest
```

The machine that runs `apply` needs the core only, with no driver and no route to a source. A worker needs the connectors its sources use, and for `odbc` an ODBC driver manager and the vendor's driver, which you install yourself under the vendor's licence.

## Defining a source

One file per source under `sources/` names the connector, its connection and every table with its key, as in the example above. A table without its own `max_age` takes the source's. Secrets appear in the connection only as placeholders such as `$ERP_PASSWORD`, filled in from the environment when `apply` runs. Nobody has to type 200 table names: `rowvioli list erp` asks the source and prints them ready to paste.

[docs/definition.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/definition.md) has every setting (load times, target names, change logs, safety limits, connector options) and what `apply` refuses.

## When a table is loaded

A table is due when it is older than its `max_age`, at a load time it names with `at`, or when somebody asks for it: `rowvioli run erp`, or `requested_at` set in `_rowvioli.tables`. A worker takes the most overdue table, reads it into a staging table, checks it, compares it with the mirror inside Postgres and publishes the difference in one transaction. A run that fails changes nothing and is tried again after a pause of 1, 2, 4, 8 minutes and so on, up to `max_age`. Every table with a key also keeps a change log, unless it is switched off, and a view `<table>__history` with every version of a row.

- [docs/loading.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/loading.md): when a table is due, a run step by step, the checks before publishing, what a person does by hand, and how workers share the work.
- [docs/target.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/target.md): the schema `_rowvioli`, the mirror with its change log and history, the comparison, how Postgres counts what is running, and what happens when something fails.

## Connectors

Four connectors ship: `postgres` in the core, and `file` (CSV, Excel, Parquet, JSON), `odbc` (any ODBC source) and `rest` (flat JSON over HTTP) as extras of the same name. Any other source is a package of its own, and the whole contract is one function that yields Arrow batches:

```python
def read(connection: dict, table: str, options: dict) -> Iterator[pyarrow.RecordBatch]:
```

[docs/connectors.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/connectors.md) has the options of each connector, licences, a custom connector complete, and the column types in the target. [docs/connector-guide.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/connector-guide.md) walks through a connector for a source whose driver is under a vendor licence.

## Operation and security

The same command at every size: cron starting `rowvioli run` every minute, `rowvioli work` as a service, or the same on more machines. The definition lives in a repository whose pipeline runs `apply`. A worker has no checkout and no file that describes a source; it brings its connectors, `ROWVIOLI_TARGET_URL` and a copy of `worker.key`. Connections are stored in the target encrypted to that key, so source passwords are on no worker and in no backup in clear text.

There is no web UI; everything a UI needs is in `_rowvioli`: the view `status`, the log `runs` and the column `requested_at` for a load now.

- [docs/operation.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/operation.md): the definition's repository, a worker as a systemd service and what it says, the target with its rights as SQL, and deploying while loads are running.
- [docs/connections.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/connections.md): connections, TLS, how they are encrypted, where the keys live, rotation, and what this protects against.

## Commands

`key new`, `apply`, `work` and `status` above are most of it. `init` creates the schema `_rowvioli` on its own, `list` prints the tables of a source, `apply --check` checks a definition without a target, and `run` loads what is due once and ends, or loads a named source or table now. `rowvioli --version` prints the version.

[docs/commands.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/commands.md) has every command with what it needs, `apply` in detail, the answer of `run` and its exit codes.

## Further documents

| File | Content |
|---|---|
| [docs/definition.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/definition.md) | Defining a source: every setting |
| [docs/loading.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/loading.md) | When a table is loaded, a run, checks, what a person does by hand, workers |
| [docs/target.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/target.md) | Target schema, history, comparing, how Postgres counts, failures |
| [docs/connections.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/connections.md) | Connections, TLS, encryption and keys |
| [docs/commands.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/commands.md) | Every command |
| [docs/operation.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/operation.md) | The definition's repository, workers, the target and its rights, deploying |
| [docs/connectors.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/connectors.md) | The connectors, licences, a custom connector, types |
| [docs/connector-guide.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/connector-guide.md) | A connector that needs licensed software, from an empty directory to a mirrored table |
| [GLOSSARY.md](https://github.com/romanhaendler/rowvioli/blob/main/GLOSSARY.md) | Terms |
| [docs/decisions.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/decisions.md) | Every decision with its reason, its price and the rejected alternative |
| [docs/measurements.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/measurements.md) | All measurements with set-up and limitations |
| [CHANGELOG.md](https://github.com/romanhaendler/rowvioli/blob/main/CHANGELOG.md) | What each version contains |
| [docs/package.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/package.md) | The package and the first version |
| [docs/open-points.md](https://github.com/romanhaendler/rowvioli/blob/main/docs/open-points.md) | What is undecided, unverified or unbuilt |
| [experiments/](https://github.com/romanhaendler/rowvioli/tree/main/experiments/) | The scripts behind the measurements |

`uv run bench/bench.py` measures the main cases at 10⁶ rows through the program.
