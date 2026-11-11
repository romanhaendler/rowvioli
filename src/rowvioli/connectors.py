"""Connector registry: `type` -> read(connection, table, options) returning Arrow batches (decision 27)."""
import adbc_driver_postgresql.dbapi as adbc
import pyarrow as pa


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def _numeric(field):
    """The driver reads `numeric` as text, and cannot write text into `numeric` (README "Types").
    The declared precision and scale become a decimal, so the staging table gets `numeric` again."""
    typmod = int(field.metadata.get(b"POSTGRESQL:typmod", b"-1"))
    if typmod < 0:
        # shortcut: unconstrained numeric with more than 38 digits before or after the point fails the run;
        # upgrade by reading such columns with a cast to a bounded type in the source query.
        return pa.decimal256(76, 38)
    p, s = (typmod - 4) >> 16, (typmod - 4) & 0xFFFF
    return pa.decimal128(p, s) if p <= 38 else pa.decimal256(p, s)


def postgres(connection, table, options):
    conn = adbc.connect(connection["url"])
    cur = conn.cursor()
    cur.execute("SELECT * FROM " + ".".join(quote(p) for p in table.split(".")))
    reader = cur.fetch_record_batch()
    numeric = {f.name for f in reader.schema if (f.metadata or {}).get(b"POSTGRESQL:type") == b"numeric"}
    schema = pa.schema([pa.field(f.name, _numeric(f)) if f.name in numeric else f for f in reader.schema])

    def batches():
        try:
            for b in reader:
                yield pa.record_batch([c.storage.cast(t.type) if t.name in numeric else c
                                       for c, t in zip(b.columns, schema)], schema=schema)
        finally:
            cur.close()
            conn.close()
    return pa.RecordBatchReader.from_batches(schema, batches())


REGISTRY = {"postgres": postgres}
