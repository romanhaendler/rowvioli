# Connectors

What a connector is, the four that ship with their options, licences, how to get one, a custom connector complete, and the column types in the target.

The whole contract is one function:

```python
def read(connection: dict, table: str, options: dict) -> Iterator[pyarrow.RecordBatch]:
    """Yield the rows of one table, chunk by chunk."""
```

| Goes in | Meaning | From |
|---|---|---|
| `connection` | where the source is and how to get in | the decrypted connection of the source |
| `table` | what to read there | the name in the definition |
| `options` | how to read, for example a separator or a page size | the definition, nothing secret |

Out come Arrow batches with a schema that stays the same, and nothing else. A connector never sees the target, a lock or another table. It has to keep two promises: deliver in chunks instead of all at once, and keep column types stable.

A connector may offer a second function, `tables(connection)`, that lists the tables of the source with their keys. Only `rowvioli list` uses it, run by a person on a machine that has the connector. The worker process never calls it. A third, `driver_version`, is a string, not a function: the version of the library the connector reads with, which a run records ([connector guide](connector-guide.md)). The shipped connectors report their package and its version, `duckdb 1.5.0`, and none when the package has no metadata.

| Connector | Covers | Built on | Needed on the worker |
|---|---|---|---|
| `postgres` | PostgreSQL | ADBC | nothing |
| `odbc` | any ODBC source; tested against PostgreSQL only | arrow-odbc | an ODBC driver manager and the vendor's driver |
| `file` | CSV, Excel, Parquet, JSON | DuckDB | access to the files |
| `rest` | flat JSON objects over HTTP, page by page | Python generator | nothing |

`postgres` and `odbc` read the whole table and know no option; `rest` knows `path`, `columns`, `page` and `rows`; `file` knows those of DuckDB's readers. An option a connector does not know fails the run, naming the table, the option and the options the connector knows (`public.customers: the option incremental is not one of the postgres connector's; it knows no option`), so `incremental = "updated"` is never taken for a load that is not incremental. A connector of your own decides for itself (decision 47).

**`odbc`** reads the whole table with `SELECT * FROM <table>`. The connection has one field, `string`, an ODBC connection string. The table name is dotted parts of letters, digits and underscores and is not quoted. The column types follow the driver's description of the columns. Without the driver manager the connector fails and says to install `unixodbc` (libodbc). `rowvioli list` reads the tables and their primary keys from `INFORMATION_SCHEMA`, so a source without it needs its tables block written by hand. It is tested against PostgreSQL through the open psqlODBC driver; SQL Server and Informix are not tested, so check the types of decimals, dates, timestamps and unbounded text on them first. A text value longer than the size the driver reports for its column (psqlODBC: 8190 bytes for `text`, raised with `MaxLongVarcharSize=<bytes>` in the connection string) fails the run instead of being cut; for columns the driver reports as unbounded, such as `varchar(max)`, rowvioli allows 1 MiB per value (untested). The tests need a driver manager and the driver `PostgreSQL Unicode`; where there is none, they skip and name `tests/odbc/run.sh`, which runs them in a container.

**`file`** reads one file per table from the directory `path` of the connection, by extension: `.csv`, `.xlsx`, `.parquet`, and `.json`, `.jsonl` or `.ndjson` for JSON. A table is the file name as written in the definition, or a pattern with `*` or `?` such as `orders_*.csv`, which reads every matching file as one table; a file that lands later arrives on the next run. A pattern reads any number of files, 50 at a time; each file's columns are checked first, a few milliseconds per file. An empty file fails and says so. A table by pattern mirrors what the directory holds now: files moved away take their rows with them, and a move of many meets the limit on deletions. A pattern needs `target_table`, and its files must be of one kind, or the run fails and names the file. The files may have different columns: a column one file lacks is empty in its rows, and a column no file has in this run is empty and, with a change log, does not go, also when the header lost it for good (dropping it from the mirror is the way to be rid of it, [Loading](loading.md#columns)); the same column with another type in two files fails the run and names the file. Without a change log a column missing from all the files stops the run, as for any table ([Loading](loading.md#the-stops)). Every file, also each match of a pattern, must lie inside `path`: a name or a match that leaves it (`../x.csv`, an absolute path, a symbolic link) fails the run and names the table. A relative `path` is resolved against the worker's working directory, so under systemd or cron write it absolute or set `WorkingDirectory`. Every option of the table except `columns` goes to DuckDB's reader as it is (`read_csv`, `read_xlsx`, `read_parquet`, `read_json`), so a European CSV is one option away:

```toml
"items.csv" = { key = ["item_no"], sep = ";", decimal_separator = ",", nullstr = "n/a",
                columns = { amount = "decimal(10,2)" } }
```

A CSV skips no line before its header unless `skip` says so. A CSV that splits into a single column fails unless `sep` is given, because that is how DuckDB reads a file whose lines have different numbers of fields; a file of one column needs `sep = ","`. A field with a quote that is never closed is read as text with the quote in it; `quote = '"'` makes such a file fail.

A JSON file holds objects, as an array or one per line. Each key becomes a column of type `jsonb` holding the value as written, nested objects and arrays too, so a type never changes between two runs; a number is read as a JSON number and is not kept as written: `10.50` arrives as `10.5` and `1E2` as `100.0`, and a change from `1.0` to `1` is no change; `columns` gives a column a DuckDB type, cast from the value's text (`columns = { id = "bigint", name = "text" }`). A number with a fraction passes through a 64-bit float, so beyond 15 to 17 significant digits it is rounded. An empty JSON file fails, since it names no column, and a string with `\u0000` fails without naming the column (a known limit).

An option the reader does not know fails the run. The options are those of DuckDB's `read_csv`, `read_xlsx`, `read_parquet` and `read_json`; for JSON, `maximum_depth` and `records` are fixed.

**`rest`** reads a JSON array of flat objects from `url` + `path`, or, with the option `rows`, from a field of the answer. The connection has `url` and optionally `token`, sent as a Bearer header. `path` is a path on the connection's host: it starts with `/`, and one that would lead the token elsewhere (`.evil.com/x`) fails the run and `apply`. A table needs `path` and `columns`, which names every column with a type: `text`, `int8`, `float8`, `bool`, `date`, `timestamp` or `timestamptz`. The mirror has the columns in the order `columns` names them. A field not named is left out, a missing field in some objects is null, and a named column that is absent from every object of an answer is empty, as an API that leaves out null fields means it. The columns named are the catalog: a column taken out of `columns` leaves the mirror and stays in the change log, and a type changed to another family goes and comes back, both by the definition (a table without a change log stops and says how to drop the column). A renamed field is a new column unless the table says `renamed`. A field that is present with `null` stays a null. A value that is not of its column's type fails the run, naming the column and the type and never the value: `readings: column temp is not float8 in every row; change the value at the source, or its type under columns`. The connector sets no timeout; `max_seconds` bounds the run. With `page = "page"` that query parameter counts from 1 and the connector asks until a page comes back empty, and fails the run if a page repeats the one before; without `page` there is one request. `rows` names the field that holds the array, one name or several joined by dots (`data`, `result.items`); without it the answer itself is the array. Paging ends when the array in the field is empty. An answer without the field, or with something else than an array of flat objects there, fails the run and names `rows`. An empty first page publishes an empty table. A `timestamptz` without a zone is read as UTC. For other paging or headers, write a [custom connector](#a-custom-connector-complete).

## Licences

rowvioli ships only code written for it and dependencies under a permissive licence; everything under another licence is installed by the operator or lives in a separate package. Three consequences follow for you:

- A connector's code is written from the source's public documentation, never taken from another project.
- Vendor drivers, SDKs and specification files are not in the package. You install them under the vendor's licence and accept its terms yourself; rowvioli accepts none for you. For `odbc` that is the ODBC driver.
- A connector that needs a GPL library or a vendor SDK is a separate package with its own licence.

The reasons are in decision 38. It is the project's rule, not legal advice. For a source whose driver or SDK is under a vendor licence, [docs/connector-guide.md](connector-guide.md) walks you through it.

## Two ways to get a connector

| Way | Set-up | In the definition | Meant for |
|---|---|---|---|
| Shipped | `pip install rowvioli[odbc]` (extras: `file`, `odbc`, `rest`) | `type = "odbc"` | The connectors in the table above. The core stays small, heavy dependencies come only on request. |
| Separate package | `pip install rowvioli-weather` | `type = "weather"` | Everything else. The package registers through an entry point. |

Installing connectors on the workers is the operator's task.

## A custom connector, complete

```python
# rowvioli_weather.py
import httpx
import pyarrow as pa

SCHEMA = pa.schema([("station", pa.string()),
                    ("time", pa.timestamp("s", tz="UTC")),  # the API sends seconds since 1970
                    ("temp", pa.float64())])

def read(connection, table, options):
    if not options["path"].startswith("/"):  # the token goes to the connection's host only
        raise Exception(f"{table}: the option path must start with /")
    with httpx.Client(base_url=connection["url"], timeout=None,  # max_seconds bounds the run
                      headers={"Authorization": "Bearer " + connection["token"]}) as client:
        page = 1
        while rows := client.get(options["path"], params={"page": page}).json():
            yield pa.RecordBatch.from_pylist(rows, schema=SCHEMA)
            page += 1
    if page == 1:  # an empty table still needs its columns
        yield pa.RecordBatch.from_pylist([], schema=SCHEMA)
```

```toml
# pyproject.toml of the connector package
[project.entry-points."rowvioli.connectors"]
weather = "rowvioli_weather"
```

```toml
# sources/weather.toml
[weather]
type    = "weather"
max_age = "1h"

[weather.connection]
url   = "https://api.example.org"
token = "$WEATHER_TOKEN"

[weather.tables]
readings = { key = ["station", "time"], path = "/v1/readings" }
```

The shipped `rest` connector does the same without code for the simple case. The columns are then named in the definition:

```toml
[weather.tables.readings]
key     = ["station", "time"]
path    = "/v1/readings"
columns = { station = "text", time = "timestamptz", temp = "float8" }
```

A connector that needs licensed software, worked through from an empty directory to a mirrored table: [docs/connector-guide.md](connector-guide.md).

## Types

The column types in the target follow from the Arrow schema the connector delivers.

- **Arrow only.** A connector names its schema. Types are never guessed from the first rows, so they cannot flip between two runs.
- **Files.** The `file` connector delivers every CSV and Excel column as text and every JSON column as `jsonb`, except those the option `columns` names with a DuckDB type, for example `columns = { amount = "decimal(10,2)" }`. Parquet keeps its own types. Giving a column a type after the first load is a change of type: with a change log the column goes and comes back, and its old values stay in the change log; without one the run stops and says how to drop the column ([Loading](loading.md#columns)). So does taking a pin out of a CSV, Excel or JSON column, which goes back to `text` or `jsonb`. A value that the type under `columns` does not take fails the run with a reason that names the file, the column and the type, not the value.
- **Decimals keep their precision and scale.** An Arrow `decimal128(p,s)` arrives as `numeric(p,s)`, from every connector, when its scale is between 0 and its precision (others need Postgres 15 and arrive as `numeric`), so a `numeric(12,2)` `137.00` stays `137.00`, and DuckDB's `decimal(10,2)` is `numeric(10,2)`. From the `postgres` connector this holds up to 38 digits; an unconstrained `numeric`, and one beyond 38 digits, arrive as `numeric` (the connector delivers them as Arrow's `decimal256`). An unconstrained `numeric` with more than 38 digits on either side of the point, `NaN` or `Infinity` fails the run, with a reason that names the column and which of these it is, and not the value (`public.n: column v has NaN or Infinity, which no decimal holds; cast it in a view of the source`, or `has a value of more than 38 digits before or after the point, the most a numeric without precision holds here`). The driver drops trailing zeros, so an unconstrained `1.10` arrives as `1.1`.
- **An existing column keeps its type.** A column whose type in the mirror differs from the source's only in precision or scale, `numeric(10,2)` where the source has `numeric`, takes the values that fit and keeps its type; on the first value that does not fit, mirror and change log are widened to the type that holds both, as for any type of the same family ([Loading](loading.md#columns)). A mirror made by 0.1.0 therefore keeps loading with its `numeric` columns. A table without a change log is widened too; only a type of another family needs a change log.
- **What the driver cannot carry from Postgres arrives as text.** The `postgres` connector reads `money` as `numeric` (the driver would deliver cents), and every type the driver would deliver as raw bytes (`inet`, `xml`, `timetz`, ranges, `bit`, `point`, `tsvector` and the like) as text, and an array of such a type as one text value, not as an array. `inet` keeps its netmask: `10.0.0.2` arrives as `10.0.0.2/32`. `bytea`, `uuid`, numbers, dates, timestamps, intervals, enums and arrays of these arrive with their own type.
- **`json` arrives as `jsonb`**, from every connector. The staging step turns it into `jsonb`, because the driver cannot write `jsonb` and `json` has no equality, so a table with it could not be compared on its second run. A mirror that has a `json` column from before goes and comes back as `jsonb` with the first run, when it has a change log; without one the run stops and says how to drop the column ([Loading](loading.md#the-stops)).
- **A NUL byte in a text value is removed**, for every connector, because Postgres cannot store it. Only top-level text columns are cleaned, not text inside a list or struct and not a `\u0000` escape inside a JSON value: those still fail the run (decision 51).
- **The driver decides the other types in the target.** ADBC creates the staging table and the mirror takes its types. `varchar(n)` arrives as `text`, and an existing `varchar(n)` column in a target table is of another family: with a change log it goes and comes back as `text`, without one the run stops. A run sees types only as the driver shows them, so a change from `text` to `varchar(20)` passes unseen. This is the price of one driver (decisions 28 and 49).
