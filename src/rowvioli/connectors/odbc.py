"""The odbc connector: expects `string`, an ODBC connection string; reads the whole table through arrow-odbc as a
stream of batches whose schema follows the driver's column descriptions. The driver is installed by the operator."""
import re

import arrow_odbc

# not quoted, since quoting differs between sources, and a plain name needs none on any of them
PLAIN = re.compile(r"\w+(\.\w+)*")


def read(connection, table, options):
    if not PLAIN.fullmatch(table):
        raise Exception(f"{table}: an odbc table name is dotted parts of letters, digits and underscores")
    return arrow_odbc.read_arrow_batches_from_odbc(
        "SELECT * FROM " + table, connection["string"],
        max_bytes_per_batch=16 * 2**20).into_pyarrow_record_batch_reader()


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
        raise Exception(f"the source has no INFORMATION_SCHEMA to list tables from, write the tables block by hand"
                        f" ({e})")
    found = {}
    for batch in reader:
        for schema, table, column in zip(*batch.to_pydict().values()):
            key = found.setdefault(f"{schema}.{table}", [])
            if column is not None:
                key.append(column)
    return {table: key or None for table, key in sorted(found.items())}
