# Open points

What is undecided, unverified or unbuilt at the release of 0.1.0 on 2026-11-17, after load times, visibility, target names, history and the first shakedown.

## Decisions for the owner

None at the moment.

Decided after the prototype and no longer open: percent-encoding a password in a URL, stopping `work`, asking what is claimable, and one `target_schema` per source (decisions 32 to 35; the rule about names is replaced by decision 39).

Decided in the second round and no longer open: new tables of the source do not arrive by themselves (decision 21), one key pair for all workers (decision 26), no second Postgres driver (decision 28), the address of the target comes from the worker's environment (decision 30), and the smaller points collected in decision 31.

## Left open

- **Seeing dead runs** (A5, `.scratch/prototype/findings.md`). A dead run's row in `runs` stays `running` without `finished_at`, and only its table shows `failed: worker lost`. If people should see dead runs as such, a second small view over `runs` is needed.

## Not verified

These follow from the design or from documentation and were not tried out. The prototype verified the model as a whole: the view and the order, the pause, requests during a run, claiming with both limits, `apply`, a process per run with `max_seconds`, whole connection blocks, row counts through ADBC, a reader during publishing, and runs killed at every step.

From the second round:

- **The behaviour during a failover.** A target address with several nodes and `target_session_attrs=read-write` works through ADBC: `init` and `status` went to the writable one of two local servers, the other read-only.
- **Windows.** The stop through Ctrl+Break and the worker's threads were written for it; no test runs there.

Unchanged from the first round:

- **Machine failure.** Nobody closes the connection then. With a container's network cut, Postgres freed the lock after 62 s through the keepalive the session asks for (`target.SESSION`); without it the lock was still held after 240 s. A real machine or a real network was not tried.
- **`client_connection_check_interval`** was measured on Linux. Postgres supports it only on some operating systems.
- **The connectors themselves**: arrow-odbc for MSSQL and Informix, DuckDB for files. The `postgres`, `file`, `odbc` and `rest` connectors are tested; `odbc` only against PostgreSQL through psqlODBC, SQL Server and Informix not at all.
- **Wide tables with many rows.** 900 columns were measured with 100,000 rows only.
- **The history view on a log some hundred times larger** than the 48 MB measured, or one that does not fit in memory (section 13).
- **The COPY from a client over a real network.** Experiment 8 filled the staging table from a client on the same machine.

## Known limits

- **Very large tables are read completely on every run.** Planned is one switch per table that reads only rows from a timestamp on and in exchange detects no deletions. It does not change the flow.
- **At 10⁷ rows a run takes over a minute.** Staging, diff and publishing add up to more than a minute before any reading.
- **No multi-core comparison** of a single table, because the staging table is a TEMP table (decision 6).
- **Change logs only ever grow.** They are on by default and nothing prunes them.
- **A load after an event in the source** needs a request from outside.
- **A table that takes longer to load than its `max_age`** is due again the moment it is published and loads without a break.
- **A table that stays broken** reads the source about ten times on the first day and once per `max_age` after that, and at each load time.
- **All workers on one target have to be equipped alike** (decision 27).
- **New tables of a source have to be added by hand.**
- **Column types without equality.** `xml` cannot be compared row by row and has to arrive as text. `json` is not on the list: the staging step turns it into `jsonb` for every connector.
- **A multi-dimensional array arrives flattened** from a Postgres source: `{{1,2},{3,4}}` becomes `{1,2,3,4}`. The driver reads it so; a view in the source that casts it to text keeps its shape.
- **Comparison happens in the target type.** If a connector delivers the same value once as `1.0` and once as `1.00` into a text column, the row counts as updated.
- **A compromised worker can read every connection.** It holds the private key and a database connection.
- **The place where `apply` runs holds every secret** in its environment.
- **An older ciphertext can be put back** by someone with write access to the target.
- **A wrongly built connection shows only when a table is loaded.** `apply` does not know the connector; it catches only a `type` near a built-in one (decision 45).
- **Removing secrets from error texts is best effort.** The program removes every value of a connection as written, stripped of surrounding whitespace and as Python quotes it, and a password in a URL or ODBC string as written and decoded; from the target's errors only the password of its address. A driver can still reformat a connection string or quote part of a value in another way. A secret of one or two characters may also be removed from inside other words of a reason, which makes it unreadable and hides nothing else; a rule for it is not worth its cost. Every value of a connection is removed, also a harmless one: with `path = "csv"` on a `file` source, reasons read `a table must be a file inside ***`.
- **The private key file has to reach every worker** once, by whatever the organisation uses for that.
- **No common point in time in the source.** Two tables are not read at the same moment.
- **A table with a key cannot have a column `_op`**, nor `_run`, `_loaded_at`, `_valid_from` or `_valid_to` with a change log. The diff, the change log and the history view use these names.
- **Dropping a change log needs `CASCADE`**, or dropping the history view first.
- **A clock set back between two runs of one table** by more than the time between them would put their rows in the wrong order in the history.
- **A table that left the definition and the table that took over its name hold different locks** (a lock is the pair of source and table). A run of the first that is still loading while the second runs can meet it on one mirror: a primary-key failure, or a doubled row in the log, at worst.
- **A change log left under a name the definition no longer has** keeps a history view that nobody updates.
- **A history view left behind under a name a new change log takes** is replaced by the next run, or the run fails if its columns do not fit.
- **An empty page in the middle of REST paging ends the load.** An empty page is how paging ends, so an API that answers one in the middle delivers a table that stops there. The limit on deletions catches a large cut, a small one passes.
- **A REST column that is absent from every row of one page fails the run.** An API that leaves out null fields can therefore fail on a page where an optional column is null in every row.
- **`timestamptz 'infinity'` from a Postgres source fails the run** with `Error occurred writing COPY data:` and nothing after it. The driver gives no cause.
- **A JSON number with a fraction passes through a 64-bit float** in the `file` connector: beyond 15 to 17 significant digits it is rounded. Whole numbers of any size and exponents arrive exactly.
- **An unterminated quote in a CSV loads with the quote kept**: `1,"Anna` followed by more lines arrives as a row whose value is `"Anna`, without an error. Forcing `quote = '"'` would fail such a file, and also one with a literal `"` in an unquoted field, which loads right today. Whoever sets `quote = '"'` gets the failure.
- **`columns` casts follow DuckDB**, for CSV and JSON: `1.7` cast to `integer` becomes `2`.
- **A JSON file holds objects.** An empty file and one of other values fail with DuckDB's words (`json_read expected records, but got non-record JSON instead.`), which do not say "empty". A file that is one object is one row.
- **The files of a pattern must all have the column**: a JSON key that one file lacks fails the run, while inside one file it is null. `*` does not match a name that starts with a dot, and `**` is one directory level, like `*`.
- **DuckDB's messages can name a value of the file** (a record with an unknown key, a value that does not cast).
- **A JSON file is read twice**, once for its columns and once for its rows; so is every file of a pattern of JSON files.
- **A REST field whose own name contains a dot cannot be named in `rows`**, and `apply` does not check `rows`: a value that is not text fails at the run.
- **The pooler check has holes.** A control connection behind a pooler in transaction mode is caught by comparing `pg_backend_pid()` in two transactions. An idle pooler hands out the same server connection and passes it; a busy one was caught in 84 of 100 checks (PgBouncer 1.26.1, eight busy neighbours; [measurements](measurements.md#14-the-pooler-check-behind-pgbouncer-in-transaction-mode)). Session mode is the requirement, the check a net.
- **Tables without a key** are replaced as a whole on every run, have no change log, and bloat until autovacuum has run.
- **Advisory locks share one number space per database.** Another application using two-key advisory locks in the same database could collide.
- **An idle worker keeps one connection to the target open**, with which it asks whether something is claimable.
- **A process per run costs about 0.18 s.** It matters only for hundreds of tiny tables per minute on one machine.
- **A worker's restart can take up to `max_seconds`**, because it lets its runs finish (decision 33).
- **The ADBC driver cannot run `SHOW`** and other statements that return rows but cannot be wrapped into `COPY`.
- **The driver decides the types in the target** (decision 28). `varchar(n)` arrives as `text` and `numeric(p,s)` as `numeric`, so a change between such types passes the schema check. An unconstrained `numeric` beyond 38 digits fails the run.

## Not built

- The web UI.
- The command `request`, reading only rows from a timestamp on, patterns for table names, and workers that serve only some sources.
- Migrating the schema from one version to the next.

The prototype's code is on branch `prototype-impl`.

## Not examined

- Whether Sling or ingestr already cover most of this.
- DuckDB as the engine of the whole program instead of only the `file` connector.
- Whether another small tool for mirroring into Postgres already works with a maximum age per table.
- The domains `rowvioli.com`, `.de`, `.io`, `.dev` and a GitHub account or organisation named `rowvioli` are not reserved; they were free on 2026-11-11.
