# A connector that needs licensed software

For a source whose driver or SDK comes under a vendor licence or the GPL: SQL Server, Informix, Oracle, SAP and the like.

The rule is [decision 38](decisions.md#38-rowvioli-ships-only-code-written-for-it-and-permissive-dependencies). For you it means: the licensed software never travels with rowvioli or with your connector. You install it on the machines that run it, and you accept its terms yourself. Everything below follows from that.

This is the project's rule and what the texts say, not legal advice.

## First question: is ODBC enough?

If the vendor offers an ODBC driver, you write no connector. Install the driver on every worker under the vendor's terms, then use `type = "odbc"`.

```sh
odbcinst -q -d                      # the ODBC drivers this machine has (unixODBC)
uv tool install "rowvioli[odbc]"
```

Start the definition with an empty tables block:

```toml
# sources/erp.toml
[erp]
type    = "odbc"
max_age = "1h"

[erp.connection]
string = "Driver={ODBC Driver 18 for SQL Server};Server=sqlsrv01;Database=erp;UID=reader;PWD=$ERP_PASSWORD"

[erp.tables]
```

Let rowvioli fill it, then load once:

```sh
export ROWVIOLI_TARGET_URL=postgresql://etl@pg01/dwh
export ERP_PASSWORD=...
rowvioli init
rowvioli key new
rowvioli list erp >> sources/erp.toml      # one line per table, with its primary key (here: from sources/, else from the target)
rowvioli apply sources/
ROWVIOLI_KEY_FILE=worker.key rowvioli run erp
rowvioli status
```

The commands were run with PostgreSQL behind the open psqlODBC driver. SQL Server and Informix are untested. Check these four things on your source before you rely on it:

- **Types.** After the first run, look at the target table (`\d raw_erp.customers` in psql). Decimals should arrive as `numeric`, dates as `date`, timestamps as `timestamp`. Look closely at SQL Server's `datetime2` and `datetimeoffset` and at Informix `DATETIME` and `MONEY`.
- **Unbounded text.** arrow-odbc needs a size limit for columns like `varchar(max)`; the connector allows 1 MiB per value, and a longer one fails the run. Neither is tested.
- **`list`.** It reads `INFORMATION_SCHEMA`. SQL Server has it, Informix does not. Without it, write the tables block by hand.
- **Error messages.** Apply once with a wrong password, run, and search the output of `run` and `status` for it. It should not be there: rowvioli removes `PWD=` and `Password=` from every reason, whatever the driver quotes. You see whether your driver quotes more than that.

## Otherwise: a package of your own

When there is no ODBC driver, or it is not good enough, the connector is a separate package. It lives outside this repo, under its own licence, and registers through an entry point.

The example below is the package the tests of this repo use, `tests/connector`, with the parts that only the tests need left out. A test checks that the two files shown here still match it. It reads no source and delivers one column `n`. Build it once from an empty directory, then put your SDK in place of the numbers.

```toml
# rowvioli-testing/pyproject.toml
[project]
name = "rowvioli-testing"
version = "0"
requires-python = ">=3.11"
dependencies = ["pyarrow"]

[project.entry-points."rowvioli.connectors"]
testing = "rowvioli_testing"

[build-system]
requires = ["uv_build>=0.8,<0.12"]
build-backend = "uv_build"
```

```python
# rowvioli-testing/src/rowvioli_testing/__init__.py
import pyarrow as pa


def read(connection, table, options):
    return batches(connection, options)


def batches(connection, options):
    yield pa.record_batch({"n": options.get("rows", [1, 2, 3])})
```

The name after `testing =` in the entry point is the `type` in the definition.

```toml
# sources/demo.toml
[demo]
type    = "testing"
max_age = "1h"

[demo.connection]
url = "testing://reader:$DEMO_PASSWORD@nowhere/demo"

[demo.tables]
numbers = { key = ["n"] }
```

Install it next to rowvioli, on every worker, and run:

```sh
uv tool install rowvioli --with ./rowvioli-testing
export ROWVIOLI_TARGET_URL=postgresql://etl@pg01/dwh
rowvioli init
rowvioli key new
DEMO_PASSWORD=secret rowvioli apply sources/
ROWVIOLI_KEY_FILE=worker.key rowvioli run
rowvioli status
```

Until rowvioli is on PyPI, put the path of a checkout in place of `rowvioli` in the first line.

**Beside a wheel that is installed already**, install the wheel again with the connector, by the same command: `uv tool install --reinstall ./rowvioli-0.1.0-py3-none-any.whl --with ./rowvioli-testing`. `uv tool install` replaces what a tool had, so name every `--with` the worker needs. With `pip`, `pip install ./rowvioli-testing` into the environment of the wheel does the same. Either way the connector is found by its entry point at the next start, and `rowvioli run` lists the installed types when one is missing. The status shows `demo numbers ok`, and `select * from raw_demo.numbers` in the target returns 1, 2, 3.

Now make it yours:

- **`read(connection, table, options)`** gets the decrypted `[demo.connection]` block as a dict, the table name as written in the definition, and every other key of the table as an option. An option's name must not be within a letter or two of one of rowvioli's settings: `apply` refuses it as a typo. Open the connection in `read` and return a generator of Arrow batches, as above. A wrong password then fails at once, before the first batch. Refuse an option the connector does not read, as the shipped ones do: fail with the table, the option and the options you know.
- **Chunks and a fixed schema.** Yield batches of a bounded size, never the whole table. Name the schema (`pa.schema([...])`) from what the source reports for the table, never from the first rows, so types do not flip between runs. Yield at least one batch, an empty one with the schema when the source has no rows: a connector that yields nothing fails the run.
- **`tables(connection)`**, optional, makes `rowvioli list` work. It returns a dict from table name to its key columns, or `None` for a table without a key: `{"dbo.Customers": ["CustomerNo"], "dbo.Notes": None}`. The shipped `odbc` connector (`src/rowvioli/connectors/odbc.py`) is a complete example of both functions.
- **The columns are the catalog.** A column your connector no longer delivers is a column that goes: for a table with a key and a change log the run takes it out of the mirror and keeps its values in the change log, and a type of another family is a column that goes and comes back. Only the shipped `file` and `rest` connectors have rules for a missing column (it is empty); a connector of your own gets the rules for a database source. If your source leaves out empty fields, deliver every column anyway, empty where it is not there, so that a missing field is not taken for a dropped column. [Loading](loading.md#columns) says what a run does with each change.
- **`driver_version`**, optional, a string at the module's top: the version of the library your connector reads with, for example `driver_version = "mylib 2.3.1"`. It is recorded with every run in `_rowvioli.runs`, with the version of rowvioli. When a run changes columns and these versions differ from those of the table's last successful run, or that run had none, the changes are recorded `by = reader`, with both versions in the note, so that a column another driver delivers differently is not taken for a change of the source. A connector that says nothing has none. The shipped connectors report the package they read with, as `<package> <version>`: `adbc-driver-postgresql` for `postgres`, `duckdb` for `file`, `httpx` for `rest` and `arrow-odbc` for `odbc`, which is not the ODBC driver the operator installed; the entry is empty when the package was installed without its metadata. All workers of a target run the same drivers, or a table's columns change with the worker that loads it ([operation](operation.md#the-target)).

## Where the licensed software lives

- **On the machine that runs it, installed by the operator.** Never in your package, its repo, or an image you pass on. Passing it on redistributes the vendor's files.
- **Your package has its own licence.** rowvioli's MIT covers rowvioli, not your package. Choose one that fits the library your package uses. A connector for a source whose SDK is under a vendor licence is looked at by a lawyer before it is published.
- **Your code is your own.** Write it from the vendor's public documentation. Do not copy or port another project's connector, whatever tool does the porting, and do not copy the vendor's examples or specification files into the repo. Name the product in plain words only, no logo.

## Testing it

Test against the vendor's developer edition, under terms you accept yourself. The acceptance is usually a setting: an environment variable such as `ACCEPT_EULA=Y` for a container, or a prompt in the installer. Whoever sets it accepts. On your own machine that is you. In CI the line sits in a workflow file, and none of the texts below says who accepts when someone else's push runs it. rowvioli's own tests therefore run only against free sources (`tests/odbc/run.sh` runs the `odbc` tests with psqlODBC in a container).

What was read on 2026-11-12:

- **Microsoft.** The SQL Server Developer edition and the ODBC driver are licensed to develop and test. Microsoft commits `ACCEPT_EULA=Y` in its own repositories. Publishing benchmark results of SQL Server needs Microsoft's written approval, so keep timings to yourself.
- **IBM.** The licence texts of the Informix Developer Edition and of the Client SDK with its ODBC driver could not be retrieved. Read them yourself before you test.

## Secrets

rowvioli removes every value of the connection from a failure reason before it stores or prints it: each text in the block as written, stripped of surrounding whitespace and as a driver quotes it inside quotes, and the password inside a URL or an ODBC string, as written and decoded. The status view and the output of `run` and `work` stay clean even when your SDK quotes the connection in its errors.

What rowvioli cannot clean is what your connector writes itself:

- Never print, log or write a connection value to a file.
- Print nothing on stdout. In a run it carries the answer to the worker.
- Stderr of a run is discarded, but `rowvioli list` shows it. Keep it free of connection values too.
