"""The file connector: expects `path`, a directory; a table is a file name in it, or a pattern with `*` or `?`
(`orders_*.csv`) that reads every matching file as one table; they must be of one kind and have the same columns.
Every file must lie inside `path`, also through a symbolic link. Reads CSV, Excel, Parquet and JSON through DuckDB by
extension (`.json`, `.jsonl` and `.ndjson` hold one object per row). Parquet keeps its own types; CSV and Excel
arrive as text and JSON as jsonb, a column per key, except the columns the option `columns` names with a DuckDB type
(a JSON value is cast from its text, so `"Anna"` loses its quotes). Every other option is a named parameter of
DuckDB's reader, such as `sep`, `skip` or `sheet`; a name that belongs to rowvioli, such as `parallel`, reaches no
connector. A CSV skips no line before its header unless `skip` says so, and one that splits into a single column
fails unless `sep` is given: that is how DuckDB reads lines with different numbers of fields."""
import glob
import re
from pathlib import Path

import duckdb
import pyarrow as pa

from ..target import quote

READERS = {".csv": "read_csv", ".xlsx": "read_xlsx", ".parquet": "read_parquet", ".json": "read_json",
           ".jsonl": "read_json", ".ndjson": "read_json"}
# a type name with an optional precision, since it is written into the query: `integer`, `decimal(10,2)`
TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_ ]*(\(\d+(,\s*\d+)?\))?")


def read(connection, table, options):
    base = Path(connection["path"])
    # a pattern is expanded here, not by DuckDB, so that every file it matches is checked like a single one
    names = sorted(glob.glob(table, root_dir=base)) if "*" in table or "?" in table else [table]
    if not names:
        raise Exception(f"{table}: no file in {connection['path']} matches")
    files = [(base / name).resolve() for name in names]
    for name, file in zip(names, files):
        if not file.is_relative_to(base.resolve()):
            raise Exception(f"{table}: a table must be a file inside {connection['path']}"
                            + (f"; {name} is not" if name != table else ""))
        if file.suffix.lower() not in READERS:
            raise Exception(f"{name}: the file connector reads {', '.join(READERS)} files")
        if not file.is_file():
            raise Exception(f"{name}: no such file in {connection['path']}")
    if len({READERS[f.suffix.lower()] for f in files}) > 1:
        raise Exception(f"{table}: matches {' and '.join(sorted({f.suffix.lower() for f in files}))} files; "
                        "a table reads files of one kind")
    reader = READERS[files[0].suffix.lower()]
    options = dict(options)
    columns = options.pop("columns", {})
    if reader in ("read_csv", "read_xlsx"):
        options["all_varchar"] = True
    if reader == "read_csv":  # else DuckDB drops the lines before the first one whose fields it likes, the header too
        options.setdefault("skip", 0)
    json = reader == "read_json"
    if json:  # every value as written: types guessed from the first rows could flip between two runs
        options.update(maximum_depth=1, records="true")
        options.setdefault("sample_size", -1)  # else a key that first appears late fails the run
    for name in options:
        if not name.isidentifier():
            raise Exception(f"{table}: {name} is not an option of DuckDB's {reader}")
    for type in columns.values():
        if not TYPE.fullmatch(type):
            raise Exception(f"{table}: {type} is not a column type")
    text = "->>'$'" if json else ""  # a JSON value is cast from its text, as in a CSV: "Anna" without the quotes
    casts = ", ".join(f'CAST({quote(c)}{text} AS {t}) AS {quote(c)}' for c, t in columns.items())
    db = duckdb.connect()
    one = f"SELECT * FROM {reader}(?" + "".join(f", {name} = ?" for name in options) + ")"
    # escaped, since DuckDB would expand *, ? and [ in a name once more and read a file nobody checked
    parts = [db.sql(one, params=[glob.escape(str(f)), *options.values()]) for f in files]
    first = dict(zip(parts[0].columns, parts[0].types))
    result = parts[0]
    for name, part in zip(names[1:], parts[1:]):
        if dict(zip(part.columns, part.types)) != first:  # one file's other columns would be lost or null
            have = [", ".join(f"{c} {t}" for c, t in zip(p.columns, p.types)) for p in (part, parts[0])]
            raise Exception(f"{table}: {name} has the columns {have[0]}, {names[0]} has {have[1]}")
        result = result.union(part.project(", ".join(quote(c) for c in first)))  # by name, not by position
    if reader == "read_csv" and len(first) == 1 and not {"sep", "delim", "delimiter"} & options.keys():
        raise Exception(f"{table}: no separator splits every line into the same number of fields; fix the lines, "
                        "or set sep (also for a file of one column) and skip (for lines before the header)")
    if casts:
        result = result.project(f"* REPLACE ({casts})")
    batches = result.to_arrow_reader()
    # DuckDB hands JSON over as text; as Arrow's json it becomes jsonb. Not by arrow_lossless_conversion: that
    # turns a hugeint into bytes and a boolean into a number
    schema = pa.schema([f.with_type(pa.json_()) if str(t) == "JSON" else f
                        for f, t in zip(batches.schema, result.types)])

    def keep_open():  # the reader needs the connection until the last batch
        try:
            for batch in batches:
                yield batch.cast(schema)
        finally:
            db.close()
    return pa.RecordBatchReader.from_batches(schema, keep_open())


def tables(connection):
    """The readable files of the directory, without keys."""
    return {p.name: None for p in sorted(Path(connection["path"]).iterdir()) if p.suffix.lower() in READERS}
