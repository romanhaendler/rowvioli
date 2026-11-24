"""The rest connector: expects `url` and, optionally, `token` (sent as a Bearer header). A table is an endpoint: the
option `path` is appended to `url`, `columns` names every column with a type (text, int8, float8, bool, date, timestamp,
timestamptz) and `page` names a query parameter that counts from 1 until a page comes back empty; a page equal to the one
before fails the run. Each response is a JSON array of flat objects and becomes one batch; with the option `rows` the
array sits in a field of a JSON object instead, `rows = "data"` or `rows = "result.items"` (names joined by dots), and a
page ends the paging when the array in the field is empty."""
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

import httpx
import pyarrow as pa

from ..contract import known_options, version

# the reader's version, so that columns another one delivers are recorded as by = reader (decision 54)
driver_version = version("httpx")

TYPES = {"text": pa.string(), "int8": pa.int64(), "float8": pa.float64(), "bool": pa.bool_(), "date": pa.date32(),
         "timestamp": pa.timestamp("us"), "timestamptz": pa.timestamp("us", tz="UTC")}


def _timestamptz(text):
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)  # shortcut: no zone means UTC, when sources differ add an option


def _timestamp(text):
    t = datetime.fromisoformat(text)
    if t.tzinfo:
        raise ValueError(f"{text} carries a zone, use timestamptz")
    return t


PARSE = {"date": date.fromisoformat, "timestamp": _timestamp, "timestamptz": _timestamptz}


def read(connection, table, options):
    known_options("rest", table, options, ("path", "columns", "page", "rows"))
    for option in ("path", "columns"):
        if option not in options:
            raise Exception(f"{table}: the option {option} is missing")
    if "rows" in options and not (isinstance(options["rows"], str) and options["rows"]):
        raise Exception(f"{table}: the option rows must be a field name")
    columns = options["columns"]
    for name, type in columns.items():
        if type not in TYPES:
            raise Exception(f"{table}: column {name}: {type} is not a type, use {', '.join(TYPES)}")
    schema = pa.schema([(name, TYPES[type]) for name, type in columns.items()])
    if not connection.get("token", "").isascii():  # httpx's own error would show the character
        raise Exception(f"{table}: the token holds a character outside ASCII")
    headers = {"Authorization": f"Bearer {connection['token']}"} if connection.get("token") else {}
    path, paged, page, previous = options["path"], "page" in options, 1, None
    address = connection["url"] + path
    here, there = urlsplit(connection["url"]), urlsplit(address)
    # the token goes to the connection's host only: `.evil.com/x` or `@host/x` would move it
    if not path.startswith("/") or (here.scheme, here.hostname, here.port) != (there.scheme, there.hostname, there.port):
        raise Exception(f"{table}: the option path must start with / and stay on the connection's host")
    while True:
        response = httpx.get(address, params={options["page"]: page} if paged else None,
                             headers=headers, timeout=None)  # max_seconds bounds the run
        if not response.is_success:
            raise Exception(f"{table}: {path} answered {response.status_code}")
        try:
            rows = response.json()
        except ValueError:
            rows = None
        for field in options["rows"].split(".") if "rows" in options else []:
            rows = rows.get(field) if isinstance(rows, dict) else None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise Exception(f"{table}: {path} must answer a JSON array of flat objects"
                            + (f" in the field {options['rows']} (option rows)" if "rows" in options else ""))
        if paged and not rows:
            if page == 1:  # an empty table still needs its columns
                yield pa.RecordBatch.from_pylist([], schema=schema)
            return
        if rows == previous:  # an API that ignores the page would otherwise be asked until max_seconds
            raise Exception(f"{table}: {path} answered page {page} like page {page - 1}, so it does not page")
        previous = rows
        arrays = []  # a column absent from every row is empty, as an API that leaves out null fields means it
        for name, type in columns.items():
            try:
                values = [r.get(name) for r in rows]
                for v in values:  # pyarrow would truncate 1.5 and take True for a number
                    if (type == "int8" and v is not None and v.__class__ is not int) or (
                            type == "float8" and v.__class__ is bool):
                        raise ValueError
                parse = PARSE.get(type)
                arrays.append(pa.array([None if v is None else parse(v) for v in values] if parse else values,
                                       TYPES[type]))
            except Exception:  # the value stays out of the reason: it would end up in the status view and the log
                raise Exception(f"{table}: column {name} is not {type} in every row; change the value at the source, "
                                "or its type under columns") from None
        yield pa.RecordBatch.from_arrays(arrays, schema=schema)
        if not paged:
            return
        page += 1
