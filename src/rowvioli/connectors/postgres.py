"""The postgres connector: expects `url` and knows no option; reads the whole table through ADBC as a stream of batches."""
import adbc_driver_postgresql.dbapi as adbc
import pyarrow as pa

from ..contract import known_options, version
from ..target import quote

# the reader's version, so that columns another one delivers are recorded as by = reader (decision 11)
driver_version = version("adbc-driver-postgresql")


def read(connection, table, options):
    known_options("postgres", table, options)
    conn = adbc.connect(connection["url"])
    cur = conn.cursor()
    name = ".".join(quote(p) for p in table.split("."))
    # the schema without running the query; each column is read as the type that arrives faithfully
    columns = ", ".join(_read_as(f) for f in cur.adbc_execute_schema("SELECT * FROM " + name))
    cur.execute(f"SELECT {columns} FROM {name}")
    reader = cur.fetch_record_batch()
    schema = pa.schema([pa.field(f.name, _decimal(f)) if _is_numeric(f) else f for f in reader.schema])

    def batches():
        try:
            for b in reader:
                yield pa.record_batch([c.storage.cast(f.type) if _is_numeric(r) else c
                                       for c, f, r in zip(b.columns, schema, reader.schema)], schema=schema)
        finally:
            cur.close()
            conn.close()
    return pa.RecordBatchReader.from_batches(schema, batches())


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
    if typmod < 0:
        # unconstrained: 38 digits on either side of the point; more fails the run (docs/connectors.md "Types")
        return pa.decimal256(76, 38)
    # the scale is 11 bits with a sign since Postgres 15: numeric(5,-2) rounds to hundreds
    p, s = (typmod - 4) >> 16, (((typmod - 4) & 0x7FF) ^ 1024) - 1024
    return pa.decimal128(p, s) if p <= 38 else pa.decimal256(p, s)
