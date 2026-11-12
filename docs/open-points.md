# Open points

What is undecided, unverified or unbuilt as of 2026-11-12, after the prototype.

## Decisions for the owner

None at the moment. The points the prototype left open are decided for 0.1 in `.scratch/v0.1/spec.md` where marked below.

Decided after the prototype and no longer open: percent-encoding a password in a URL, stopping `work`, asking what is claimable, and one `target_schema` per source (decisions 32 to 35).

Decided in the second round and no longer open: new tables of the source do not arrive by themselves (decision 21), one key pair for all workers (decision 26), no second Postgres driver (decision 28), the address of the target comes from the worker's environment (decision 30), and the smaller points collected in decision 31.

## Left open by the prototype

From `.scratch/prototype/findings.md`:

- **"Workers wait and retry" when the target is gone** (E11). The prototype's loop has no retry and would end with a traceback. With `Restart=always` the service manager would bring it back, which was not tried. **Decided for 0.1:** the worker itself waits two seconds and connects again; no service manager is needed for it.
- **Schema versions** (B5). In the prototype `init` recreates the view and creates missing tables, and nothing migrates. `docs/package.md` proposes that the program refuses to start on another version. **Decided for 0.1:** every command refuses another schema version and names both. The version is 2 since load times (decision 36). Migration waits for the first version that needs it.
- **Progress** (A4), for example `485,000 of about 1,000,000 rows`, was not built. 0.1 builds it in the status view.
- **Seeing dead runs** (A5). A dead run's row in `runs` stays `running` without `finished_at`, and only its table shows `failed: worker lost`. If people should see dead runs as such, a second small view over `runs` is needed.
- **A traceback on stderr** (F4). A run process that crashes writes it unscrubbed to the inherited stderr. **Decided for 0.1:** the run process catches everything and turns it into a scrubbed reason; if it still dies, the worker reports `worker lost`.
- **`runs.definition`** (B4), the hash of the definition, was never filled, and `key_id` is read by nobody. 0.1 fills the hash and uses `key_id` to pick among several private keys during rotation.

## Not verified

These follow from the design or from documentation and were not tried out. The prototype verified the model as a whole: the view and the order, the pause, requests during a run, claiming with both limits, `apply`, a process per run with `max_seconds`, whole connection blocks, row counts through ADBC, a reader during publishing, and runs killed at every step.

From the second round:

- **Progress from `pg_stat_progress_copy`.** Experiment 8 read it from a second connection as a superuser. Whether a role without special rights sees the rows of another session was not checked.
- **A target address with several nodes** through ADBC, and the behaviour during a failover.
- **ADBC from a Linux client.** Experiment 8 and the prototype ran on macOS against Postgres in Docker.
- **Entry points** for connectors. Standard Python, not tried here.

Unchanged from the first round:

- **Machine or network failure.** Nobody closes the connection then. Release of the lock depends on TCP keepalive, expected after about 60 s. `data-extractor` could not reproduce this locally either.
- **`client_connection_check_interval`** was measured on Linux. Postgres supports it only on some operating systems.
- **The connectors themselves**: arrow-odbc for MSSQL and Informix, DuckDB for files. `data-extractor` has experience with ODBC. Only the `postgres` connector was played in the prototype.
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
- **A load after an event in the source** needs a request from outside.
- **A table that takes longer to load than its `max_age`** is due again the moment it is published and loads without a break.
- **A table that stays broken** reads the source about ten times on the first day and once per `max_age` after that, and at each load time.
- **All workers on one target have to be equipped alike** (decision 27).
- **New tables of a source have to be added by hand.**
- **Column types without equality.** `json` and `xml` cannot be compared row by row and have to arrive as `jsonb` or text.
- **Comparison happens in the target type.** If a connector delivers the same value once as `1.0` and once as `1.00` into a text column, the row counts as updated.
- **A compromised worker can read every connection.** It holds the private key and a database connection.
- **The place where `apply` runs holds every secret** in its environment.
- **An older ciphertext can be put back** by someone with write access to the target.
- **A wrongly built connection shows only when a table is loaded.** `apply` does not know the connector.
- **Removing secrets from error texts is best effort.** A driver can reformat a connection string or quote part of a value in ways the program does not recognise.
- **The private key file has to reach every worker** once, by whatever the organisation uses for that.
- **No common point in time in the source.** Two tables are not read at the same moment.
- **Tables without a key** are replaced as a whole on every run, have no change log, and bloat until autovacuum has run.
- **Advisory locks share one number space per database.** Another application using two-key advisory locks in the same database could collide.
- **An idle worker keeps one connection to the target open**, with which it asks whether something is claimable.
- **A process per run costs about 0.18 s.** It matters only for hundreds of tiny tables per minute on one machine.
- **A worker's restart can take up to `max_seconds`**, because it lets its runs finish (decision 33).
- **The ADBC driver cannot run `SHOW`** and other statements that return rows but cannot be wrapped into `COPY`.
- **The driver decides the types in the target** (decision 28). `varchar(n)` arrives as `text` and `numeric(p,s)` as `numeric`, so a change between such types passes the schema check. An unconstrained `numeric` beyond 38 digits fails the run.

## Not built

The program. A throwaway prototype (`.scratch/prototype/`, code on branch `prototype-impl`) played the model to answer seven questions: `init`, `key new`, `apply`, `run`, `work`, the schema, the status view and the `postgres` connector. It is not the start of the program. Not built even there:

- `list`, `apply --check`, decisions 32 to 35,
- adding a new column to the mirror, `log = false`, table-level `max_delete_share` and `max_seconds`, connector options,
- the `odbc`, `file` and `rest` connectors,
- the web UI.

## Not examined

- Whether Sling or ingestr already cover most of this.
- DuckDB as the engine of the whole program instead of only the `file` connector.
- Whether another small tool for mirroring into Postgres already works with a maximum age per table.
- A formal trademark search for the name `rowvioli` (see `docs/package.md`).
