"""The postgres connector: expects `url`, reads the whole table through ADBC as a stream of batches."""
import adbc_driver_postgresql.dbapi as adbc
import pyarrow as pa


def read(connection, table, options):
    conn = adbc.connect(connection["url"])
    cur = conn.cursor()
    cur.execute("SELECT * FROM " + ".".join('"' + p.replace('"', '""') + '"' for p in table.split(".")))
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


def _is_numeric(field):
    return (field.metadata or {}).get(b"POSTGRESQL:type") == b"numeric"


def _decimal(field):
    """The driver reads `numeric` as text and cannot write text into `numeric` (README "Types"), so it becomes a
    decimal with the column's precision and scale, and the target gets `numeric` again."""
    typmod = int((field.metadata or {}).get(b"POSTGRESQL:typmod", b"-1"))
    if typmod < 0:
        # unconstrained: 38 digits on either side of the point; more fails the run (README "Types")
        return pa.decimal256(76, 38)
    p, s = (typmod - 4) >> 16, (typmod - 4) & 0xFFFF
    return pa.decimal128(p, s) if p <= 38 else pa.decimal256(p, s)
