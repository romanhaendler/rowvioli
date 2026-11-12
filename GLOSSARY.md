# Glossary

The binding vocabulary of the concept. If a term changes, it changes here and in `README.md`.

| Term | Meaning |
|---|---|
| **Source** | A source system with a connection and a list of tables. By convention one file `sources/<name>.toml` in the definition. |
| **Source table** | A table, file or endpoint of the source that a connector delivers as rows. |
| **Target** | The one PostgreSQL database that holds the mirrors and the bookkeeping. The word is used for nothing else. |
| **Target table** | The table in the target that exactly one source table is loaded into. It belongs to exactly one source. Its name is the last part of the source table's name in lower case (`dbo.Customers` → `customers`); a file's name loses its extension (`customers.csv` → `customers`). |
| **Mirror** | The content of the target table: what the source table looked like at the last successful run. |
| **Change log** | Second table `<target table>__log`, kept for every table with a key unless switched off. Every run appends what was inserted (`I`), updated (`U`) or deleted (`D`). Nothing is ever removed from it. |
| **Key** | The columns that identify a row. Named in the definition. |
| **Definition** | The directory of source files plus the public key. It names every table. `apply` writes it into the target. |
| **Connection** | Everything a connector needs to reach its source: address, user, password or token. A block in the definition, stored in the target as one ciphertext per source. |
| **Secret** | A single value that must not be in the definition, such as a password or a token. It comes from the environment when `apply` runs and replaces a `$NAME` placeholder in a connection. |
| **Worker key** | The key pair for connections. The public key is a file next to the definition and encrypts. The private key is a file on each worker and decrypts. |
| **Maximum age** | `max_age`: how old a mirror may get. Set per source or per table. |
| **Load time** | `at`: a time of day at which a table is due, in the table's time zone (`timezone`). Set per source or per table. A request the clock makes. |
| **Age** | The time since a table was last published. |
| **Due** | A table is due when the time computed from its facts has come: at once if never attempted, at the request if one came after the last run began, at the next load time after the last run began, one maximum age after the last success, or one pause after the last unsuccessful run. Computed on every query, never stored. |
| **Pause** | The wait after a run that did not succeed: one minute, then doubling, never longer than the maximum age. |
| **Request** | Asking for a load now by setting `requested_at` on a table. |
| **Run** | Loading one table once, in a process of its own. One row in `_rowvioli.runs`. |
| **Run status** | `running`, `ok` or `failed`, as stored in `_rowvioli.runs`. `dead` is never stored: it is computed. |
| **Table status** | `new`, `loading`, `ok` or `failed`. Computed in the view `_rowvioli.status`. |
| **Attempts** | Counter on a table: runs since the last success. |
| **Worker** | A process that looks for claimable tables (due, and within `parallel` and `max_running`) and starts a run for each. It is stateless and brings only its connectors, the address of the target and the private key. |
| **Slot** | One table a worker can load at a time. The number of slots per worker is `--slots`. |
| **Control connection** | The one connection to the target on which a run does everything: hold the lock, fill the staging table, check, compare, publish. |
| **Table lock** | A session-level advisory lock in Postgres per target table, held on the control connection. It ends with the connection. |
| **Counting lock** | A short lock that makes sure only one worker at a time counts and claims. |
| **Claim** | The step in which a run counts the running tables, takes the table lock of the most overdue table and counts the attempt. |
| **Staging table** | TEMP table of a run holding the current content of the source table. Visible only on the run's connection. |
| **Diff** | TEMP table of a run holding the rows that differ between staging table and mirror, each marked `I`, `U` or `D`. |
| **Publish** | The one transaction that writes the diff to the change log, applies it to the mirror and records the success. |
| **Dead** | A run that is recorded as `running` while nobody holds its table lock. Its table shows as `failed` with the reason `worker lost`. |
| **Connector** | One function, `read`, that attaches one kind of source. Installed on the workers by the operator. |
| **Chunk** | A portion of rows, as large as the connector makes it (about 16 MB with ADBC), that a connector delivers as an Arrow batch and that is written to the staging table as a whole. |

## Terms deliberately avoided

| Not | But | Reason |
|---|---|---|
| Job | source, table or run | "Job" meant all three at different points in the discussion. |
| Order, queue, waiting | due | Nothing waits in a queue. A table is due or it is not. |
| Schedule, scheduler | maximum age, load time | The definition says how old, and at which times of day. No next time is stored. |
| Scan, pattern | list of tables | Tables are named. Nothing is discovered while the system runs. |
| Secret store | connection | There is no table of secrets. A source has one encrypted connection. |
| Destination | address of the source | "Target" means the Postgres database only. |
| Mode, load strategy | (none) | There is only one flow. |
| Hash | (none) | Rows are compared column by column in the target. |
| Heartbeat, lease, fencing | table lock | The connection itself is the sign of life. |
| Landing | staging table | One term is enough. |
