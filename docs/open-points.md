# Open points

What is undecided, unverified or unbuilt as of 2026-11-11, after the second round of the discussion.

## Decisions for the owner

None at the moment.

Decided in the second round and no longer open: new tables of the source do not arrive by themselves (decision 21), one key pair for all workers (decision 26), no second Postgres driver (decision 28), the address of the target comes from the worker's environment (decision 30), and the smaller points collected in decision 31.

## Not verified

These follow from the design or from documentation and were not tried out.

From the second round:

- **The model as a whole.** A maximum age per table, the view that computes what is due, the order by how far a table misses its target, and the growing pause exist on paper only.
- **Claiming in its new form.** Experiment 5 handed out waiting runs with one counting lock per source. Due tables, one counting lock for the whole target and the total limit `max_running` were not tried.
- **`apply`**: idempotence, disabling what is missing, filling in placeholders, one transaction.
- **Progress from `pg_stat_progress_copy`.** Experiment 8 read it from a second connection as a superuser. Whether a role without special rights sees the rows of another session was not checked.
- **One process per run**, including ending a hanging run after `max_seconds` and the cost of starting a process per table.
- **Requesting a load while the table is loading.** That it then loads once more follows from comparing two points in time.
- **Encrypting a whole connection block.** Experiment 7 encrypted a single named value.
- **A target address with several nodes** through ADBC, and the behaviour during a failover.
- **Row counts through ADBC.** Experiment 8 took all counts from queries, not from the driver.
- **ADBC from a Linux client.** Experiment 8 ran on macOS against Postgres in Docker.
- **Entry points** for connectors. Standard Python, not tried here.

Unchanged from the first round:

- **A concurrent reader during publishing.** That consumers never see an empty table follows from one transaction and MVCC. Experiment 8 checked from a second connection that nothing is visible before the COMMIT. No test with a reader running alongside exists.
- **A killed process cannot publish.** Follows from the transaction ending with the connection.
- **Machine or network failure.** Nobody closes the connection then. Release of the lock depends on TCP keepalive, expected after about 60 s. `data-extractor` could not reproduce this locally either.
- **`client_connection_check_interval`** was measured on Linux. Postgres supports it only on some operating systems.
- **Removing secrets from error texts.**
- **The connectors themselves**: ADBC for Postgres as a source, arrow-odbc for MSSQL and Informix, DuckDB for files. `data-extractor` has experience with the first two.
- **Composite keys.** Only a single-column key was measured.
- **Wide tables with many rows.** 900 columns were measured with 100,000 rows only.
- **A view that computes validity periods from the change log**, and its speed on a long history.
- **The COPY from a client over a real network.** Experiment 8 filled the staging table from a client on the same machine.
- **Adding a column inside the publishing transaction** while consumers read.

## Known limits

- **Very large tables are read completely on every run.** Planned is one switch per table that reads only rows from a timestamp on and in exchange detects no deletions. It does not change the flow.
- **At 10⁷ rows the path is slower than `hpdl`.** Staging, diff and publishing add up to more than a minute before any reading.
- **No multi-core comparison** of a single table, because the staging table is a TEMP table (decision 6).
- **Change logs only ever grow.** They are on by default and nothing prunes them.
- **No fixed times.** "Load at six" cannot be said. A load after an event needs a request from outside.
- **A table that takes longer to load than its `max_age`** is due again the moment it is published and loads without a break.
- **A table that stays broken** reads the source about ten times on the first day and once per `max_age` after that.
- **All workers on one target have to be equipped alike** (decision 27).
- **New tables of a source have to be added by hand.**
- **Column types without equality.** `json` and `xml` cannot be compared row by row and have to arrive as `jsonb` or text.
- **Comparison happens in the target type.** If a connector delivers the same value once as `1.0` and once as `1.00` into a text column, the row counts as updated.
- **A compromised worker can read every connection.** It holds the private key and a database connection.
- **The place where `apply` runs holds every secret** in its environment.
- **An older ciphertext can be put back** by someone with write access to the target.
- **A wrongly built connection shows only when a table is loaded.** `apply` does not know the connector.
- **Removing secrets from error texts is best effort.** A driver can reformat a connection string in ways the program does not recognise.
- **The private key file has to reach every worker** once, by whatever the organisation uses for that.
- **No common point in time in the source.** Two tables are not read at the same moment.
- **Tables without a key** are replaced as a whole on every run, have no change log, and bloat until autovacuum has run.
- **Advisory locks share one number space per database.** Another application using two-key advisory locks in the same database could collide.
- **An idle worker keeps one connection to the target open**, with which it looks for due tables.
- **The ADBC driver cannot run `SHOW`** and other statements that return rows but cannot be wrapped into `COPY`.

## Not built

Everything. In particular:

- the program and all connectors,
- the schema `_rowvioli` beyond the parts used in experiment 5,
- the status view,
- the web UI,
- the example definition,
- tests and benchmark.

## Not examined

- Whether Sling or ingestr already cover most of this.
- DuckDB as the engine of the whole program instead of only the `file` connector.
- Whether another small tool for mirroring into Postgres already works with a maximum age per table.
- A formal trademark search for the name `rowvioli` (see `docs/package.md`).
