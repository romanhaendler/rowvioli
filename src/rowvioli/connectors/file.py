"""The file connector: expects `path`, a directory; a table is a file name in it. Reads CSV, Excel and Parquet
through DuckDB by extension. Parquet keeps its own types; CSV and Excel arrive as text, except the columns the option
`columns` names with a DuckDB type. Every other option is a named parameter of DuckDB's reader, such as `sep` or
`sheet`."""
import re
from pathlib import Path

import duckdb
import pyarrow as pa

from ..target import quote

READERS = {".csv": "read_csv", ".xlsx": "read_xlsx", ".parquet": "read_parquet"}
# a type name with an optional precision, since it is written into the query: `integer`, `decimal(10,2)`
TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_ ]*(\(\d+(,\s*\d+)?\))?")


def read(connection, table, options):
    file = Path(connection["path"]) / table
    reader = READERS.get(file.suffix.lower())
    if reader is None:
        raise Exception(f"{table}: the file connector reads {', '.join(READERS)} files")
    if not file.is_file():
        raise Exception(f"{table}: no such file in {connection['path']}")
    options = dict(options)
    columns = options.pop("columns", {})
    if reader != "read_parquet":
        options["all_varchar"] = True
    for name in options:
        if not name.isidentifier():
            raise Exception(f"{table}: {name} is not an option of DuckDB's {reader}")
    for type in columns.values():
        if not TYPE.fullmatch(type):
            raise Exception(f"{table}: {type} is not a column type")
    casts = ", ".join(f'CAST({quote(c)} AS {t}) AS {quote(c)}' for c, t in columns.items())
    db = duckdb.connect()
    result = db.sql(f"SELECT *{f' REPLACE ({casts})' if casts else ''} FROM {reader}(?"
                    + "".join(f", {name} = ?" for name in options) + ")", params=[str(file), *options.values()])
    batches = result.to_arrow_reader()

    def keep_open():  # the reader needs the connection until the last batch
        try:
            yield from batches
        finally:
            db.close()
    return pa.RecordBatchReader.from_batches(batches.schema, keep_open())


def tables(connection):
    """The readable files of the directory, without keys."""
    return {p.name: None for p in sorted(Path(connection["path"]).iterdir()) if p.suffix.lower() in READERS}

