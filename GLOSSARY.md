# Glossary

The binding vocabulary of the concept. If a term changes, it changes here and in `README.md`.

| Term | Meaning |
|---|---|
| **Source** | A source system with a connection and a selection of tables. One file `sources/<name>.toml` in the jobs repo. |
| **Source table** | A table, file or endpoint of the source that a connector delivers as rows. |
| **Target table** | The table in the target that exactly one source table is loaded into. It belongs to exactly one source. |
| **Mirror** | The content of the target table: what the source table looked like at the last successful run. |
| **Change log** | Optional second table `<target table>__log`. Every run appends what was inserted (`I`), updated (`U`) or deleted (`D`). Nothing is ever removed from it. |
| **Key** | The columns that identify a row. Defaults to the primary key of the source. |
| **Staging table** | TEMP table of a run holding the current content of the source table. Visible only on the run's connection. |
| **Diff** | TEMP table of a run holding the rows that differ between staging table and mirror, each marked `I`, `U` or `D`. |
| **Order** | The request to load a source or a single table. One row in `_rowvioli.orders`. |
| **Run** | Loading one table for one order. One row in `_rowvioli.runs`. |
| **Run status** | `waiting`, `running`, `ok`, `failed` or `dead`. |
| **Attempt** | Counter of a run. After a dead run, a new waiting run is created with the next attempt, up to the third. |
| **Worker** | A process that claims waiting runs and executes them. |
| **Slot** | One table a worker can load at a time. The number of slots per worker is `--slots`. |
| **Control connection** | The one connection to the target on which a run does everything: hold the lock, fill the staging table, check, compare, publish. |
| **Table lock** | A session-level advisory lock in Postgres per target table, held on the control connection. It ends with the connection. |
| **Counting lock** | A short lock per source that makes sure only one worker at a time counts and claims. |
| **Claim** | The step in which a worker detects dead runs, counts the running tables of a source and takes the table lock of the next waiting run. |
| **Publish** | The one transaction that writes the diff to the change log, applies it to the mirror and marks the run `ok`. |
| **Dead** | A run that is recorded as `running` while nobody holds its table lock. |
| **Submitter** | Whoever creates an order: a scheduler, a web UI or a person. |
| **Jobs repo** | The Git repository with source files, custom connectors, the schedule and the pinned program version. |
| **Load host** | A machine with a checkout of the jobs repo, an environment file, drivers and the program. |
| **Secret** | A named value a source needs to connect, usually a connection string with a password. |
| **Secret store** | The table `_rowvioli.secrets` in the target. It holds secrets as ciphertext only. |
| **Worker key** | The key pair of the secret store. The public key is in the jobs repo and encrypts. The private key is a file on each load host and decrypts. |
| **Connector** | Two functions, `tables` and `read`, that attach one kind of source. |
| **Chunk** | A portion of a few thousand rows that a connector delivers and that is written to the staging table as a whole. |

## Terms deliberately avoided

| Not | But | Reason |
|---|---|---|
| Job | source, order or run | "Job" meant all three at different points in the discussion. |
| Mode, load strategy | (none) | There is only one flow. |
| Hash | (none) | Rows are compared column by column in the target. |
| Heartbeat, lease, fencing | table lock | The connection itself is the sign of life. |
| Landing | staging table | One term is enough. |
