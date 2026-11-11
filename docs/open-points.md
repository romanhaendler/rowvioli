# Open points

What is undecided, unverified or unbuilt as of 2026-11-11.

## Decisions for the owner

| Question | Proposal |
|---|---|
| **New tables in the source.** With `include = ["dbo.*"]` they appear in the target automatically. | Keep it. Whoever does not want it lists tables one by one. |
| **Tables that disappear from the source.** | Report them in the answer and leave the target table in place. |
| **Change log on by default?** | Off. It is switched on per source or table. |
| **Cross-table consistency.** Tables of a source are published at different moments. | Accept. If needed later, an explicit group of a few tables. |
| **Target address in the environment** rather than in the source file. | Keep it, so that one file serves test and production. |
| **One key pair for all workers**, or one per network zone. | One. Split only if a zone must not be able to read the secrets of another. |
| **A second Postgres driver** next to ADBC for the control connection. | Decide when building. |

## Not verified

These follow from the design or from documentation and were not tried out.

- **A concurrent reader during publishing.** That consumers never see an empty table follows from one transaction and MVCC. No test with a reader running alongside exists.
- **A killed process cannot publish.** Follows from the transaction ending with the connection.
- **Machine or network failure.** Nobody closes the connection then. Release of the lock depends on TCP keepalive, expected after about 60 s. `data-extractor` could not reproduce this locally either.
- **`client_connection_check_interval`** was measured on Linux. Postgres supports it only on some operating systems.
- **Listing tables from an order** in one transaction with `FOR UPDATE SKIP LOCKED`, and `submit --wait`.
- **The limit of three attempts.**
- **Restarting a worker for a new program version** between two tables, and installing versions side by side with uv.
- **A `git pull` while loads are running.** Source files are read at the start of a table, which is uncritical. What a changed program version does to a running process is unknown.
- **Claiming restricted to the sources a worker can load** (decision 19).
- **The secret store around the encryption.** The encryption itself was tried out (experiment 7). Storing, the commands, key rotation and removing secrets from error texts were not.
- **Entry points** for connectors. Standard Python, not tried here.
- **The connectors themselves**: ADBC for Postgres, arrow-odbc for MSSQL and Informix, DuckDB for files. `data-extractor` has experience with the first two.
- **Composite keys.** Only a single-column key was measured.
- **Wide tables with many rows.** 900 columns were measured with 100,000 rows only.
- **A view that computes validity periods from the change log**, and its speed on a long history.
- **The COPY from a client over the network.** Filling the staging table was measured inside the database.
- **Adding a column inside the publishing transaction** while consumers read.

## Known limits

- **Very large tables are read completely on every run.** Planned is one switch per table that reads only rows from a timestamp on and in exchange detects no deletions. It does not change the flow.
- **At 10⁷ rows the path is slower than `hpdl`.** Staging, diff and publishing add up to more than a minute before any reading.
- **No multi-core comparison** of a single table, because the staging table is a TEMP table (decision 6).
- **Column types without equality.** `json` and `xml` cannot be compared row by row and have to arrive as `jsonb` or text.
- **Comparison happens in the target type.** If a connector delivers the same value once as `1.0` and once as `1.00` into a text column, the row counts as updated.
- **Types inferred from dicts** can differ between runs and then fail the schema check.
- **A compromised load host can read every secret.** It holds the private key and a database connection.
- **An older ciphertext can be put back** by someone with write access to the secret store.
- **A lost private key** means all secrets have to be set again.
- **Removing secrets from error texts is best effort.** A driver can reformat a connection string in ways the program does not recognise.
- **The private key file has to reach every load host** once, by whatever the organisation uses for that.
- **No common point in time in the source.** Two tables are not read at the same moment.
- **Tables without a key** are replaced as a whole on every run, have no change log, and bloat until autovacuum has run.
- **Advisory locks share one number space per database.** Another application using two-key advisory locks in the same database could collide.
- **An idle worker keeps at least one connection to the target open**, because claiming happens on a connection.

## Not built

Everything. In particular:

- the program and all connectors,
- the schema `_rowvioli` beyond the parts used in experiment 5,
- the status view,
- the web UI,
- the example jobs repo and its start scripts,
- tests and benchmark.

## Not examined

- Whether Sling or ingestr already cover most of this.
- DuckDB as the engine of the whole program instead of only the `file` connector.
- A formal trademark search for the name `rowvioli` (see `docs/package.md`).
