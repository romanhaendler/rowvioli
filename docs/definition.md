# Defining a source

How a source is written down: the file, what follows from it, every setting and what `apply` refuses.

One file per source, by convention. It names the connector, the connection and every table.

```toml
# sources/erp.toml
[erp]
type          = "odbc"
target_schema = "raw_erp"
max_age       = "1h"
parallel      = 4

[erp.connection]
string = "Driver={ODBC Driver 18 for SQL Server};Server=sqlsrv01;Database=erp;UID=reader;PWD=$ERP_PASSWORD"

[erp.tables]
"dbo.Customers"  = { key = ["customer_no"] }
"dbo.Items"      = { key = ["item_no"], log = false }
"dbo.Orders"     = { key = ["order_no"], max_age = "5m" }
"dbo.OrderLines" = { key = ["order_no", "line_no"] }
"sales.Customers" = { key = ["customer_no"], target_table = "sales_customers" }
"hr.Staff"        = { key = ["staff_no"], target_schema = "raw_hr" }
```

What follows from it:

- Every listed table gets a target table in `raw_erp`, named after the last part of its name in lower case: `dbo.Customers` becomes `raw_erp.customers`. A file loses its extension: `customers.csv` becomes `customers`. A table says where it lives: `sales.Customers` would also become `customers`, so `target_table` names it `sales_customers`; `hr.Staff` sets `target_schema` and becomes `raw_hr.staff`. Nothing else is loaded. A new table in the source arrives when somebody adds its name.
- The definition gives no target name twice. A table takes three names in its schema, its own, `<name>__log` and `<name>__history`, and `apply` and `list` (when it reads a definition) fail when two tables of the definition, of whichever sources, would take the same one. The error names both tables and says to set `target_table` at one of them. Since Postgres cuts names at 63 bytes and the history view adds `__history`, a target table may have 54 bytes, a schema 63 (also `raw_<name>` of a long source name). Neither may be empty, and the schema is not `_rowvioli`. No name the definition gives (source name, source table, key column, `target_schema`, `target_table`) may hold a control character (C0, DEL, C1, U+2028, U+2029): `apply`, `apply --check` and `list` fail and name the file, the setting and the name with the character as an escape, such as `\x1b`. A name already in a target keeps loading until the definition is applied again, which `apply` refuses until the name is changed. Sources may share a schema. The view `__history` begins with the first load of the table under its name.
- When `apply` finds that a loaded table gets another target name, it says so and moves nothing: the old tables stay where they are, and the next run builds new ones. [What a person does by hand](loading.md#what-a-person-does-by-hand) keeps the old ones.
- `dbo.Orders` is never older than five minutes, the other tables never older than an hour.
- At most four tables of this source load at the same time, across all workers.
- Every table with a key gets a change log, except `dbo.Items`, where it is switched off. A change log lets the run follow the source's columns, types and key by itself ([Columns](loading.md#columns)); a table without one stops at a column that is gone or of another family.
- The password is not in the file. `$ERP_PASSWORD` is filled in from the environment when `apply` runs. The whole connection block is then encrypted and stored in the target.

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `type` | source | | Connector: `postgres`, `odbc`, `file`, `rest`, or the name of an installed connector package. |
| `connection` | source | | Everything the connector needs to reach the source. The fields are defined by the connector. Values may contain `$NAME` placeholders. See [Connections](connections.md). |
| `max_age` | source or table | | How old the mirror may get, for example `5m`, `1h`, `1d`. Required at source level. |
| `at` | source or table | none | Load times: times of day at which the table is due whatever its age, for example `["06:00", "14:00"]`. A table's list replaces the source's, and `[]` switches it off. A load after an event in the source is a request, not a load time: see [Loading now](loading.md#loading-now). |
| `timezone` | source or table | | The time zone the load times are meant in, for example `"Europe/Berlin"`. Required where `at` is not empty. There is no default. |
| `tables` | source | | The tables to load, by name. |
| `target_schema` | source or table | `raw_<name>` | Schema of the target tables. At the source it is the default of its tables. |
| `target_table` | table | last part of the name | Name of the target table. Refused at the source: it can belong to one table only. |
| `parallel` | source | 2 | Maximum number of tables of this source loading at the same time. |
| `key` | table | none | Columns that identify a row. Without a key the table is replaced as a whole. |
| `log` | source or table | on | Keep a change log. `log = false` switches it off. Tables without a key never have one. |
| `renamed` | table | none | Columns the source renamed, as `{ new = "old" }`, for a rename the data cannot prove. See below. |
| `max_delete_share` | source or table | 0.5 | The run aborts if a larger share of the rows would disappear. Without a key: if the table would shrink by more. |
| `max_seconds` | source or table | 3600 | A hanging run is ended after this time. It is the one bound of a run: no connector sets a timeout of its own. |

**`renamed`** states a rename where the data cannot prove it, such as a flag, a small table or a key column: `"dbo.Customers" = { key = ["customer_no"], renamed = { city = "town" } }`. It is a setting of a table, never of a source. It acts only when the old column is gone from the source and the new one has come, and does nothing otherwise, so it can stay in the definition. A run loads by the definition as it was when it claimed the table: `renamed` applied while a run loads acts from the next run, and if the loading run already saw the new name, the old column has gone with its values kept in the change log and the new one has come. State it before the source renames, or before the next run after that. The old column is renamed in the mirror and in the change log with no row written, and a consumer's view on it keeps working. `apply` refuses an old name stated twice and a value that is not a table of `new = "old"`; a run fails when the two columns are of different families, or when the change log already has a column of the new name ([The stops](loading.md#the-stops)). On a table without a change log it renames the mirror's column. For a file or REST table it works as for any table. To rename a key column, change `key` to the new name in the same apply: `key = ["id"], renamed = { id = "customer_no" }`. Without `renamed` a renamed key column is another key: the old column stays in the change log, and the history view reads the rows before and after by their own key. The data prove a rename of other columns by themselves ([Columns](loading.md#columns)), so `renamed` is optional.

**Where the definition names the columns it is the catalog.** For a REST table every column is named under `columns`; for a file table only the columns it names are, and the others keep the type the file brings (text for CSV and Excel, `jsonb` for JSON, its own for Parquet). A type under `columns` that changes to another family, also a first type for a CSV column that was loaded as `text`, makes the column go and come back in one run, with the old values under `<name>__<run>` in the change log, recorded `by = definition`; within a family it is fitted and widened as for any column. A column taken out of a REST table's `columns` leaves the mirror and stays in the change log, as a column a database source drops. A field named under `columns` that is missing from the data is empty and never goes, in a REST table and in a file, also when no file of a pattern has it; in a file it comes after the file's own columns. So a misspelt name under `columns` is an empty column of its own beside the one it meant, which keeps the file's type; a misspelt key column stops the run, since its key is null. Every change a run makes to the columns of a REST table is `by = definition`. A pin taken out of a CSV, Excel or JSON table's `columns` is a change of type by the definition: the column goes back to `text` or `jsonb`, by the same rules as a pin that changes. A pin taken out of a Parquet column whose own type is of another family stops instead, with the hint to pin it and the drop as the way out, since the run keeps no memory of the pin and a Parquet file's own types can change. A table without a change log stops at all of this, and its reason says how to drop the column.

Any other key, at source or table level, is passed to the connector unchanged as an option, for example `path` for a REST connector. `renamed` is the one setting that is never passed on. A table's option overrides the source's of the same name. The names in the table above belong to rowvioli, so a connector cannot have an option called `at` or `timezone`, and a name at the wrong level, such as `key` at a source, fails `apply`. So does a name that is one or two letters from a setting of rowvioli, such as `max_agee`: it is almost certainly a typo, and the table would run with the default. So does a `type` one letter from `postgres`, `file`, `odbc` or `rest`, and `postgresql`, unless a connector of that name is installed where `apply` runs (a connector of your own named `jdbc` passes once it is installed there); `postgis` and every other type pass, since `apply` does not know the connectors.

Nobody has to type 200 table names and keys. `rowvioli list erp` asks the source and prints them in this format, ready to paste. It is a helper for people. Nothing in the running system calls it. It prints every table of the source, so to add tables its output replaces the lines of the `tables` block; below the old lines it gives TOML's `Cannot overwrite a value`. Settings a table already had are carried over by hand. With no `sources/` here it reads the source from the target, so a new source is applied with an empty `tables` block, listed on a worker's machine and applied again.
