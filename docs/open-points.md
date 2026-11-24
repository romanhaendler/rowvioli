# Open points

What is undecided, unverified or unbuilt at the release of 0.2.0 on 2026-11-18, after load times, visibility, target names, history, three shakedowns and the first mirror out of the box.

## Decisions for the owner

None at the moment.

Decided after the prototype and no longer open: percent-encoding a password in a URL, stopping `work`, asking what is claimable, and one `target_schema` per source (decisions 32 to 35; the rule about names is replaced by decision 39).

Decided in the second round and no longer open: new tables of the source do not arrive by themselves (decision 21), one key pair for all workers (decision 26), no second Postgres driver (decision 28), the address of the target comes from the worker's environment (decision 30), and the smaller points collected in decision 31.

Closed by decision 54: a REST column that is absent from every row of a page, and the files of a pattern that do not all have a column, no longer fail the run. The column is empty there, and with a change log it never goes.

Closed after the shakedown before the merge of schema changes: a primary key that a person changed by hand before the upgrade is no longer taken for a change of key on the first run after it; the run tells the two by the definition of the table's last successful run or by the change log, and asks where neither tells ([A key](loading.md#columns)).

Closed by ticket 12 of schema changes: a column gone for good from the files of a table with a change log leaves the mirror by the drop that [What a person does by hand](loading.md#what-a-person-does-by-hand) gives, with its history kept.

Closed by decision 55: a consumer's table that inherits from a mirror keeps its rows ([What a person does by hand](loading.md#what-a-person-does-by-hand)).

## Left open


## Not verified

These follow from the design or from documentation and were not tried out. The prototype verified the model as a whole: the view and the order, the pause, requests during a run, claiming with both limits, `apply`, a process per run with `max_seconds`, whole connection blocks, row counts through ADBC, a reader during publishing, and runs killed at every step.

From the second round:

- **The behaviour during a failover.** A target address with several nodes and `target_session_attrs=read-write` works through ADBC: `init` and `status` went to the writable one of two local servers, the other read-only.
- **Windows.** The stop through Ctrl+Break and the worker's threads were written for it; no test runs there.

Unchanged from the first round:

- **Machine failure.** Nobody closes the connection then. With a container's network cut, Postgres freed the lock after 62 s through the keepalive the session asks for (`target.SESSION`); without it the lock was still held after 240 s. A real machine or a real network was not tried.
- **`client_connection_check_interval`** was measured on Linux. Postgres supports it only on some operating systems.
- **The connectors themselves**: arrow-odbc for MSSQL and Informix, DuckDB for files. The `postgres`, `file`, `odbc` and `rest` connectors are tested; `odbc` only against PostgreSQL through psqlODBC, SQL Server and Informix not at all.
- **Wide tables with many rows.** A whole run was measured on 300 columns with 100,000 rows (about 11 s) and 300,000 rows (about 40 s), roughly linear, most of it the read from the source (section 15, ticket 16). Not measured: 900 columns in a whole run, a million rows of this width, the other connectors.
- **The history view on a log some hundred times larger** than the 48 MB measured, or one that does not fit in memory (section 13).
- **The time a large change log is locked** while a type is widened or the rows of a column are written. That is a measurement for `bench/`, run when the owner asks.
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
- **Removing secrets from error texts is best effort.** The program removes every value of a connection as written, stripped of surrounding whitespace and as Python quotes it, and a password in a URL or ODBC string as written and decoded; from the target's errors only the password of its address. A driver can still reformat a connection string or quote part of a value in another way. A secret of one or two characters may also be removed from inside other words of a reason, which makes it unreadable and hides nothing else; a rule for it is not worth its cost. Every value of a connection is removed, also a harmless one, except the `path` of a `file` connection (decision 47).
- **The private key file has to reach every worker** once, by whatever the organisation uses for that.
- **No common point in time in the source.** Two tables are not read at the same moment.
- **A table with a key cannot have a column `_op`**, nor `_run`, `_loaded_at`, `_valid_from` or `_valid_to` with a change log. The diff, the change log and the history view use these names, and `renamed` cannot give them.
- **Dropping a change log needs `CASCADE`**, or dropping the history view first.
- **A clock set back between two runs of one table** by more than the time between them would put their rows in the wrong order in the history.
- **A table that left the definition and the table that took over its name hold different locks** (a lock is the pair of source and table). A run of the first that is still loading while the second runs can meet it on one mirror: a primary-key failure, or a doubled row in the log, at worst.
- **A change log left under a name the definition no longer has** keeps a history view that nobody updates.
- **A history view left behind under a name a new change log takes** is replaced by the next run, or the run fails if its columns do not fit.
- **An empty page in the middle of REST paging ends the load.** An empty page is how paging ends, so an API that answers one in the middle delivers a table that stops there. The limit on deletions catches a large cut, a small one passes.
- **`timestamptz 'infinity'` from a Postgres source fails the run** with `Error occurred writing COPY data:` and nothing after it. The driver gives no cause.
- **A JSON number with a fraction passes through a 64-bit float** in the `file` connector: beyond 15 to 17 significant digits it is rounded. Whole numbers of any size and exponents arrive exactly.
- **An unterminated quote in a CSV loads with the quote kept**: `1,"Anna` followed by more lines arrives as a row whose value is `"Anna`, without an error. Forcing `quote = '"'` would fail such a file, and also one with a literal `"` in an unquoted field, which loads right today. Whoever sets `quote = '"'` gets the failure.
- **`columns` casts follow DuckDB**, for CSV and JSON: `1.7` cast to `integer` becomes `2`.
- **A JSON file holds objects.** A file of other values (`[1, 2]`, or `[]`) fails with DuckDB's words (`json_read expected records, but got non-record JSON instead.`); a file of no bytes says that it is empty. A file that is one object is one row.
- **`*` does not match a name that starts with a dot**, and `**` is one directory level, like `*`.
- **A field named under `columns` that a file lacks fails the read with DuckDB's words** (`Binder Error: Column "zz" in REPLACE list not found in FROM clause`).
- **Each file of a pattern is checked before it is read**, about 3 ms per file: 10,000 files take half a minute before the first row. A pattern reads 50 files at a time; open files under Linux were not measured.
- **A JSON file is read twice**, once for its columns and once for its rows; so is every file of a pattern of JSON files.
- **A REST field whose own name contains a dot cannot be named in `rows`**, and `apply` does not check `rows`: a value that is not text fails at the run.
- **The pooler check was tried with PgBouncer alone**, in one version and one pool size, idle and with up to 16 busy neighbours, and idle handing five waiting server connections round-robin ([measurements](measurements.md#14-the-pooler-check-behind-pgbouncer-in-transaction-mode)). Another pooler (Odyssey, PgCat, Supavisor) was not tried; one that hands a server connection at random to the next client passes the check by chance, as often as it gives the control connection's own back to it. Session mode is the requirement.
- **Tables without a key** are replaced as a whole on every run, have no change log, and bloat until autovacuum has run.
- **Advisory locks share one number space per database.** Another application using two-key advisory locks in the same database could collide.
- **An idle worker keeps one connection to the target open**, with which it asks whether something is claimable.
- **A process per run costs about 0.18 s.** It matters only for hundreds of tiny tables per minute on one machine.
- **A worker's restart can take up to `max_seconds`**, because it lets its runs finish (decision 33).
- **A source can keep computing the read of a run that was ended** (after `max_seconds`, a lost target or a hard kill) until it notices the closed connection. A Postgres source notices when it next sends rows, so a query that computes long before its rows arrive runs to its end, beside the retry.
- **A full disk on the target can read as `connection to the target lost`**. When the write-ahead log cannot grow, Postgres stops with a PANIC and restarts: the run has the message but can no longer store it. Elsewhere a full disk fails the run with Postgres's message, `could not extend file ...: No space left on device`.
- **A claim finds a dead run by walking `runs` back from the newest row** to the table's own newest, under the lock all claims share: 1.3 ms when 24,000 runs came since, 11 ms at 200,000 (the whole table scanned took 8 ms). An index on the table and the run would bound it; it needs a migration of the schema, which is not built.
- **The ADBC driver cannot run `SHOW`** and other statements that return rows but cannot be wrapped into `COPY`.
- **The driver decides the types in the target** (decisions 28 and 49). `varchar(n)` arrives as `text`, so a change from `text` to `varchar(n)` passes unseen, and an existing `varchar(n)` target column is of another family than `text`: with a change log it goes and comes back, without one it stops. A `numeric(p,s)` beyond 38 digits arrives as `numeric` in a new mirror. An unconstrained `numeric` beyond 38 digits, `NaN` or `Infinity` fails the run, and the reason says which. A column widened to plain `numeric` reads without trailing zeros (`3.00` reads `3`). Through ODBC, psqlODBC describes an unconstrained `numeric` as `numeric(28,6)`, and the value arrives cut to six decimals.

Schema changes (decision 54):

- **A declared length of the source is not recorded.** Arrow carries none, so `varchar(20)` and `varchar(200)` are both `text`, and a change of a length leaves no trace. The same holds for the source's constraints, defaults and comments: a mirror has none of them.
- **A change by hand is dated when it is noticed**, by the next run that publishes, and not at all while its table fails.
- **A person who changes the primary key and the definition by hand and keeps the change log leaves a seam nobody recorded.**
- **A primary key from before the upgrade that nothing in the target tells about stops its table once.** Where the definition changed since the table's last successful run and the change log could have been written under either key (only its first rows, say), the run asks for the comment on `_op` that says which. Without a change log it takes the definition's key, which replaces the mirror as a whole either way, and records `by = definition`.
- **A column that a person dropped from the change log stops the run with `is not in the change log`** while the mirror keeps it, as a person's own column does: the change log no longer says that it was the source's. The way out is the drop from the mirror.
- **A reason never shows a value of the source, as far as the program can tell one.** A value that a type under `columns` does not take names the table, the column and the type; a `numeric` that no decimal holds (`NaN`, `Infinity`, more than 38 digits on a side) from the `postgres` connector names its column, whatever Arrow's message says; a value that Postgres quotes in its message, from the source or the target, is written `"***"` (`invalid input syntax for type integer: "***"`). An ODBC driver's message is withheld by its SQLSTATE, not its words: a data exception (class `22`, SQL Server's `Conversion failed when converting the varchar value '…'` among them) and a `RAISE` give a reason without the message; tried with psqlODBC alone, in `tests/odbc/run.sh`. Not covered: a connector of one's own whose message holds a value, and an ODBC driver's message with a value under another SQLSTATE. No rule covers them, since SQL Server and MySQL quote names in single quotes as values, and a rule broad enough would hide names. A message raised under a consumer's function (`raise exception 'bad row %', NEW` in a trigger on the target, an error in a function a source view calls) is withheld, and the reason names the function, in every language whose frames Postgres names in its context (PL/pgSQL, SQL, PL/Python, PL/Perl; the last two tried on Postgres's wording alone, since the test image has neither). A function in C, or in a language that names no frame, is not told from Postgres's own code: its message is shown as Postgres's are, with a quoted value written `"***"`.
- **A column name longer than 63 bytes stops its table.** Postgres keeps 63 bytes of a name, and the definition cannot give a delivered column another name: the way out is in the source, a view or a file's header. A Postgres source cuts such a name itself, so a run never sees it there.
- **A retired column is recognised by its name**, `<name>__<digits>` beside a column `<name>` of the change log, and not by the columns table, so that a run does not need the record. A source column with such a name stops the run with the way out.
- **Two columns that swap names, or a name reused in the run its column was renamed, are not seen by any loader.** Every row of the two is a `U`.
- **A rename the data prove needs 20 rows and 5 different values**, strict on purpose, since a false proof points a consumer's view at another column. A small table, a flag and two candidates are never proven; `renamed` states them. Nothing is proven for a table without a key or a change log, or for a file or REST source.
- **A file or REST connector of one's own gets the rules of a database source**: a column it stops delivering is a column that goes. Only the shipped `file` and `rest` connectors treat a missing column as empty.
- **The columns table has no tamper evidence.** A person with the right to write the change log can change its rows.
- **A column that goes, or a type of another family, costs one change log row per row**, and a changed key two and a rewrite of the mirror: "what changed yesterday" on such a change log lists every row (40 changes of a table of 100,000 rows gave 4.2 million log rows, 383 MB). Widening can rewrite mirror and change log under an exclusive lock and outlast `max_seconds` once. A view on a history view stops changes to any column of it. A statement prepared on a mirror fails after its columns change, until it is prepared again. An upgrade that delivers a type in another family writes a row per row on every affected table once.
- **A grant on a history view that its grantee passed on with the grant option** is given again by the worker's role when a run builds the view anew, so a later `REVOKE ... CASCADE` from that grantee no longer takes it.
- **The columns table keeps a renamed column's old name for the moments before the rename**, where the history view of the mirror already shows the new one: `was` is the bridge ([History](target.md#history)).
- **A source table dropped and created anew with other columns** looks like rows that go: the run stops with the share of rows that would be deleted, and the reason says that the source table may have been replaced or emptied and that `max_delete_share = 1.0` on the table lets one run through. The program cannot tell a replaced table from a broken source.
- **A change log is never ended by the program**: `log = false` and a key taken away still stop while one exists.

## Not built

- The web UI.
- The command `request`, reading only rows from a timestamp on, patterns for table names, and workers that serve only some sources.
- Migrating the schema from a version older than 3. `init` has one step, version 3 to 4 (decision 54); a target older than 3 is refused.

The prototype's code is on branch `prototype-impl`.

## Not examined

- Whether Sling or ingestr already cover most of this. A persona's answer, a lead and not a fact: they cover the loading (more sources, incremental, CDC; their documentation checked on 2026-11-17), not the freshness model. The second half is from memory and unchecked.
- DuckDB as the engine of the whole program instead of only the `file` connector.
- Whether another small tool for mirroring into Postgres already works with a maximum age per table.
- The domains `rowvioli.com`, `.de`, `.io`, `.dev` and a GitHub account or organisation named `rowvioli` are not reserved; they were free on 2026-11-11.
