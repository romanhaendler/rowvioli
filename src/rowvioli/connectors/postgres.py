"""The postgres connector: expects `url` and knows no option; reads the whole table through ADBC as a stream of batches."""
import adbc_driver_postgresql.dbapi as adbc
import pyarrow as pa
import pyarrow.compute as pc

from ..contract import known_options, version
from ..target import quote

# the reader's version, so that columns another one delivers are recorded as by = reader (decision 54)
driver_version = version("adbc-driver-postgresql")
# a timestamp's infinity as the driver reads it: Postgres's largest number moved to Arrow's epoch, wrapped around. It
# cannot write it again ("Error occurred writing COPY data"); -infinity and a date's infinity it writes as they were
INFINITY = -2**63 + 946_684_800_000_000 - 1


def read(connection, table, options):
    known_options("postgres", table, options)
    conn = adbc.connect(connection["url"])
    cur = conn.cursor()
    name = ".".join(quote(p) for p in table.split("."))
    # the schema without running the query; each column is read as the type that arrives faithfully
    columns = ", ".join(_read_as(f) for f in cur.adbc_execute_schema("SELECT * FROM " + name))
    cur.execute(f"SELECT {columns} FROM {name}")
    # the driver manager's own reader: an error while rows arrive keeps Postgres's SQLSTATE and fields, which decide
    # what of its message a reason shows (decision 54, item 8); fetch_record_batch() gives Arrow's, with the text alone
    reader = cur._results.reader
    schema = pa.schema([pa.field(f.name, _decimal(f)) if _is_numeric(f) else f for f in reader.schema])

    def batches():
        try:
            for b in reader:
                for f, c in zip(reader.schema, b.columns):
                    c = c.flatten() if pa.types.is_list(f.type) else c  # an array of timestamps too
                    if pa.types.is_timestamp(c.type) and pc.any(pc.equal(c.view(pa.int64()), INFINITY)).as_py():
                        raise Exception(f"{table}: column {f.name} has infinity, which the driver cannot write into a "
                                        f"timestamp{'tz' if c.type.tz else ''} of the target; cast it in a view of "
                                        "the source")
                yield pa.record_batch([_cast(table, c, f) if _is_numeric(r) else c
                                       for c, f, r in zip(b.columns, schema, reader.schema)], schema=schema)
        finally:
            cur.close()
            conn.close()
    return pa.RecordBatchReader.from_batches(schema, batches())


def _cast(table, column, field):
    """A numeric's text as a decimal. Arrow's message for one that is none (`The string 'nan' is not a valid
    decimal256 number`) holds the value, which would end up in the status view and the log: the column instead, for
    any failed cast, so that no wording of Arrow's can show a value."""
    digits = max(field.type.precision - field.type.scale, 0)
    try:
        # Arrow wraps a value of far more digits than the decimal holds without an error (1.5e400 arrived as 0); the
        # digits from the first that is not 0, since Postgres writes 0.12 for numeric(2,2)
        if pc.any(pc.match_substring_regex(column.storage, rf"^-?0*[1-9]\d{{{digits}}}")).as_py():
            raise pa.ArrowInvalid
        return column.storage.cast(field.type)
    except pa.ArrowInvalid:
        odd = pc.any(pc.match_substring_regex(column.storage, "nan|inf", ignore_case=True)).as_py()
        has = ("NaN or Infinity, which no decimal holds" if odd else "a value of more than 38 digits before or after "
               "the point, the most a numeric without precision holds here")
        raise Exception(f"{table}: column {field.name} has {has}; cast it in a view of the source") from None


def tables(connection):
    """Every table outside the system schemas as `schema.table`, with its primary key in key order or None."""
    with adbc.connect(connection["url"]) as conn, conn.cursor() as cur:
        cur.execute(r"""
            SELECT n.nspname || '.' || c.relname,
                   (SELECT array_agg(a.attname::text ORDER BY k.ord)
                      FROM pg_index i, unnest(i.indkey) WITH ORDINALITY k(attnum, ord), pg_attribute a
                     WHERE i.indrelid = c.oid AND i.indisprimary AND a.attrelid = c.oid AND a.attnum = k.attnum)
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
               AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\_%'
             ORDER BY 1""")
        return dict(cur.fetchall())


def _read_as(field):
    """The column in the select list. `money` arrives as cents in an integer, so it is read as `numeric`. A type
    the driver cannot name arrives as its wire bytes (Arrow's opaque over binary), so it is read as text; an
    array of such a type arrives as one text value, not as an array. Every other type is read as it is (measured in tests/test_run.py)."""
    column, type = quote(field.name), (field.metadata or {}).get(b"POSTGRESQL:type")
    if type in (b"money", b"_money"):
        return f"{column}::numeric{'[]' if type == b'_money' else ''} AS {column}"
    item = field.type.value_type if pa.types.is_list(field.type) else field.type
    if isinstance(item, pa.OpaqueType) and pa.types.is_binary(item.storage_type):
        return f"{column}::text AS {column}"
    return column


def _is_numeric(field):
    return (field.metadata or {}).get(b"POSTGRESQL:type") == b"numeric"


def _decimal(field):
    """The driver reads `numeric` as text and cannot write text into `numeric` (docs/connectors.md "Types"), so it
    becomes a decimal with the column's precision and scale: decimal128 up to 38 digits, which the target keeps,
    decimal256 beyond and for an unconstrained `numeric`, which arrive as `numeric`."""
    typmod = int((field.metadata or {}).get(b"POSTGRESQL:typmod", b"-1"))
    # the scale is 11 bits with a sign since Postgres 15: numeric(5,-2) rounds to hundreds
    p, s = (typmod - 4) >> 16, (((typmod - 4) & 0x7FF) ^ 1024) - 1024
    if typmod < 0 or p > 76:
        # unconstrained, or more digits than any decimal: 38 digits on either side of the point; more fails the run
        # (docs/connectors.md "Types")
        return pa.decimal256(76, 38)
    return pa.decimal128(p, s) if p <= 38 else pa.decimal256(p, s)
