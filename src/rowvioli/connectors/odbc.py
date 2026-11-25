"""The odbc connector: expects `string`, an ODBC connection string, and knows no option; reads the whole table through arrow-odbc as a
stream of batches whose schema follows the driver's column descriptions. The driver is installed by the operator."""
import re

import pyarrow as pa

try:
    import arrow_odbc
except OSError as e:  # no driver manager: arrow-odbc's own message is a dlopen path
    raise ImportError("the ODBC driver manager is missing; install unixodbc (libodbc)") from e

from ..contract import known_options, version

# the reader's version, so that columns another one delivers are recorded as by = reader (decision 54); the ODBC
# driver the operator installed is not in it
driver_version = version("arrow-odbc")

# not quoted, since quoting differs between sources, and a plain name needs none on any of them
PLAIN = re.compile(r"\w+(\.\w+)*")


def read(connection, table, options):
    known_options("odbc", table, options)
    if not PLAIN.fullmatch(table):
        raise Exception(f"{table}: an odbc table name is dotted parts of letters, digits and underscores")
    # shortcut: 1 MiB per text value, a longer one fails the run; when sources hold more, add an option
    reader = arrow_odbc.read_arrow_batches_from_odbc(
        "SELECT * FROM " + table, connection["string"],
        max_bytes_per_batch=16 * 2**20, max_text_size=2**20, map_schema=read_as).into_pyarrow_record_batch_reader()
    dates = {i for i, f in enumerate(reader.schema) if f.metadata == DATE}
    schema = pa.schema([f.with_type(pa.date32()).remove_metadata() if i in dates else f
                        for i, f in enumerate(reader.schema)])

    def rows():
        try:
            yield from reader
        except Exception as e:
            raise without_value(e, table) from None

    def batches():
        for b in rows():
            yield pa.record_batch([day(table, c, f.name) if i in dates else c
                                   for i, (c, f) in enumerate(zip(b.columns, schema))], schema=schema)
    return pa.RecordBatchReader.from_batches(schema, batches())


# the mark of a date read as text, which read() casts back
DATE = {b"rowvioli:date": b"text"}


def read_as(schema):
    """Every float read as a double. arrow-odbc takes a float of a precision up to 24 for a single, and psqlODBC
    describes float8 with 17, its digits, so 1e300 arrived as Infinity; a double holds every single too, and the
    schema says nothing more that would tell them apart. Every date read as its text, yyyy-mm-dd as ODBC writes it:
    psqlODBC gives a date's infinity and -infinity as 0000-00-00, which arrived as a date struct of the day of the
    run (ticket 17)."""
    return pa.schema([f.with_type(pa.float64()) if pa.types.is_float32(f.type) else
                      f.with_type(pa.string()).with_metadata(DATE) if pa.types.is_date32(f.type) else f for f in schema])


def day(table, column, name):
    """A date read as text, as a date; one that is none fails naming the column, never the value."""
    try:
        return column.cast(pa.date32())
    except pa.ArrowInvalid:
        raise Exception(f"{table}: column {name} has a date the driver gives as no date, as psqlODBC gives infinity "
                        "and -infinity; cast it in a view of the source") from None


def without_value(e, table):
    """Decision 54, item 8: a driver's record says its SQLSTATE, which decides in the reason; arrow-odbc's own text of
    a value it cannot hold in Arrow ends in the value (`Timestamp is not representable in arrow: 9999-12-31 ...`,
    `Lossy representation of value: ...`), so only what comes before it stays, with the table."""
    if re.search(r"\bState: [^,]{5}, Native error: ", str(e)):
        return e
    first = re.sub(r"^External error: ", "", str(e).split("\n")[0])  # Arrow's word for an error of the stream
    return Exception(f"{table}: {first.split(': ')[0].strip()}")


def tables(connection):
    """Every base table as `schema.table`, with its primary key in key order or None, from INFORMATION_SCHEMA."""
    conn = arrow_odbc.connect(connection["string"])
    try:
        reader = conn.read_arrow_batches("""
            SELECT t.TABLE_SCHEMA, t.TABLE_NAME, k.COLUMN_NAME
              FROM INFORMATION_SCHEMA.TABLES t
              LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS c
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME AND c.CONSTRAINT_TYPE = 'PRIMARY KEY'
              LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k ON k.TABLE_SCHEMA = c.TABLE_SCHEMA
               AND k.TABLE_NAME = c.TABLE_NAME AND k.CONSTRAINT_NAME = c.CONSTRAINT_NAME
             WHERE t.TABLE_TYPE = 'BASE TABLE'
               AND UPPER(t.TABLE_SCHEMA) NOT IN ('INFORMATION_SCHEMA', 'PG_CATALOG', 'SYS')
             ORDER BY k.ORDINAL_POSITION""")
    except arrow_odbc.Error as e:
        raise Exception(f"the tables could not be read from INFORMATION_SCHEMA, write the tables block by hand;"
                        f" loading is not affected ({e})")
    found = {}
    for batch in reader:
        for schema, table, column in zip(*batch.to_pydict().values()):
            key = found.setdefault(f"{schema}.{table}", [])
            if column is not None:
                key.append(column)
    return {table: key or None for table, key in sorted(found.items())}
