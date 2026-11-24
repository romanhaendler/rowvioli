"""The file connector: expects `path`, a directory; a table is a file name in it, or a pattern with `*` or `?`
(`orders_*.csv`) that reads every matching file as one table; they must be of one kind, and a column one of them
lacks is empty in its rows.
Every file must lie inside `path`, also through a symbolic link. Reads CSV, Excel, Parquet and JSON through DuckDB by
extension (`.json`, `.jsonl` and `.ndjson` hold one object per row). Parquet keeps its own types; CSV and Excel
arrive as text and JSON as jsonb, a column per key, except the columns the option `columns` names with a DuckDB type
(a JSON value is cast from its text, so `"Anna"` loses its quotes). Every other option is a named parameter of
DuckDB's reader, such as `sep`, `skip` or `sheet`; a name that belongs to rowvioli, such as `parallel`, reaches no
connector. A CSV skips no line before its header unless `skip` says so, and one that splits into a single column
fails unless `sep` is given: that is how DuckDB reads lines with different numbers of fields. An empty file fails."""
import functools
import glob
import itertools
import re
from pathlib import Path

import duckdb
import pyarrow as pa

from ..contract import OWN_TYPE, version
from ..target import quote

# the reader's version, so that columns another one delivers are recorded as by = reader (decision 54)
driver_version = version("duckdb")

READERS = {".csv": "read_csv", ".xlsx": "read_xlsx", ".parquet": "read_parquet", ".json": "read_json",
           ".jsonl": "read_json", ".ndjson": "read_json"}
# a type name with an optional precision, since it is written into the query: `integer`, `decimal(10,2)`
TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_ ]*(\(\d+(,\s*\d+)?\))?")
# the files of a pattern DuckDB reads at once; at most so many are open
FILES_PER_READ = 50
# a cast that fails: DuckDB's own error, or Arrow's with its message once batches are read
CONVERSION = (duckdb.ConversionException, OSError)


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
        if not file.stat().st_size:  # else DuckDB reads it as a CSV of one column
            raise Exception(f"{name}: the file is empty")
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

    def relation(path, **extra):
        named = {**options, **extra}
        return db.sql(f"SELECT * FROM {reader}(?" + "".join(f", {name} = ?" for name in named) + ")",
                      params=[path, *named.values()])
    # escaped, since DuckDB would expand *, ? and [ in a name once more and read a file nobody checked
    paths = [glob.escape(str(f)) for f in files]
    # each file's columns; its relation goes at once, since it holds the file open
    shapes = {path: dict(zip(part.columns, map(str, part.types))) for path, part in zip(paths, map(relation, paths))}
    first = {}  # the columns of all files, in the order they first appear; a file without one has it empty
    for name, shape in zip(names, shapes.values()):
        for column, type in shape.items():
            if first.setdefault(column, type) != type:
                raise Exception(f"{table}: {name} has the column {column} as {type}, an earlier file as "
                                f"{first[column]}")
    if reader == "read_csv" and len(first) == 1 and not {"sep", "delim", "delimiter"} & options.keys():
        raise Exception(f"{table}: no separator splits every line into the same number of fields; fix the lines, "
                        "or set sep (also for a file of one column) and skip (for lines before the header)")

    def order(present):
        return ", ".join(quote(c) if c in present else f"NULL::{t} AS {quote(c)}" for c, t in first.items())

    def rows(group, cast=True):  # the columns by name, not by position, then the casts
        if reader == "read_xlsx":  # its reader takes no list
            part = functools.reduce(lambda a, b: a.union(b), (relation(p).project(order(shapes[p])) for p in group))
        else:
            present = {c for p in group for c in shapes[p]}
            # else the read of the list would drop or null one file's other columns
            by_name = {"union_by_name": True} if any(shapes[p].keys() != present for p in group) else {}
            part = relation(group, **by_name).project(order(present))
        return part.project(f"* REPLACE ({casts})") if casts and cast else part

    def uncast(e):
        """DuckDB's message for a value a cast does not take holds the value, which would end up in the status view
        and the log: the reason names the column instead, found by trying each cast. Any other error as it is."""
        if isinstance(e, OSError) and not str(e).startswith("Conversion Error"):
            return e
        for group in groups:
            part = rows(group, cast=False)
            for c, t in columns.items():
                if part.filter(f"{quote(c)}{text} IS NOT NULL AND TRY_CAST({quote(c)}{text} AS {t}) IS NULL").limit(1) \
                        .fetchall():
                    return Exception(f"{table}: column {c} is not {t} in every row; change the value in the file, or "
                                     "its type under columns")
        return Exception(f"{table}: a value in the file does not convert to the type its column is read as")
    # a few files per read, one read after the other: DuckDB opened up to 600 files of one list at once, and a
    # union of more than 333 files is too deep for it
    groups = [paths[i:i + FILES_PER_READ] for i in range(0, len(paths), FILES_PER_READ)]
    result = rows(groups[0])
    try:
        batches = result.to_arrow_reader()
    except CONVERSION as e:
        raise uncast(e) from None
    # DuckDB hands JSON over as text; as Arrow's json it becomes jsonb. Not by arrow_lossless_conversion: that
    # turns a hugeint into bytes and a boolean into a number
    schema = pa.schema([f.with_type(pa.json_()) if str(t) == "JSON" else
                        f.with_metadata(OWN_TYPE) if reader == "read_parquet" and f.name not in columns else f
                        for f, t in zip(batches.schema, result.types)])

    def keep_open():  # the reader needs the connection until the last batch
        try:
            for group in itertools.chain([batches], (rows(g).to_arrow_reader() for g in groups[1:])):
                for batch in group:
                    yield batch.cast(schema)
        except CONVERSION as e:
            raise uncast(e) from None
        finally:
            db.close()
    return pa.RecordBatchReader.from_batches(schema, keep_open())


def tables(connection):
    """The readable files of the directory, without keys."""
    return {p.name: None for p in sorted(Path(connection["path"]).iterdir()) if p.suffix.lower() in READERS}
