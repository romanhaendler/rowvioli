"""The rest connector: expects `url` and, optionally, `token` (sent as a Bearer header). A table is an endpoint: the
option `path` is appended to `url`, `columns` names every column with a type (text, int8, float8, bool, date, timestamp,
timestamptz) and `page` names a query parameter that counts from 1 until a page comes back empty. Each response is a
JSON array of flat objects and becomes one batch."""
from datetime import date, datetime, timezone

import httpx
import pyarrow as pa

TYPES = {"text": pa.string(), "int8": pa.int64(), "float8": pa.float64(), "bool": pa.bool_(), "date": pa.date32(),
         "timestamp": pa.timestamp("us"), "timestamptz": pa.timestamp("us", tz="UTC")}


def _timestamptz(text):
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)  # shortcut: no zone means UTC, when sources differ add an option


PARSE = {"date": date.fromisoformat, "timestamp": datetime.fromisoformat, "timestamptz": _timestamptz}


def read(connection, table, options):
    columns = options["columns"]
    for name, type in columns.items():
        if type not in TYPES:
            raise Exception(f"{table}: column {name}: {type} is not a type, use {', '.join(TYPES)}")
    schema = pa.schema([(name, TYPES[type]) for name, type in columns.items()])
    headers = {"Authorization": f"Bearer {connection['token']}"} if connection.get("token") else {}
    path, page = options["path"], 1
    while True:
        response = httpx.get(connection["url"] + path, params={options["page"]: page} if "page" in options else None,
                             headers=headers)
        if response.status_code != 200:
            raise Exception(f"{table}: {path} answered {response.status_code}")
        rows = response.json()
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise Exception(f"{table}: {path} must answer a JSON array of flat objects")
        if "page" in options and not rows:
            return
        arrays = []
        for name, type in columns.items():
            try:
                values = [r.get(name) for r in rows]
                parse = PARSE.get(type)
                arrays.append(pa.array([None if v is None else parse(v) for v in values] if parse else values,
                                       TYPES[type]))
            except Exception as e:
                raise Exception(f"{table}: column {name} is not {type}: {e}") from None
        yield pa.RecordBatch.from_arrays(arrays, schema=schema)
        if "page" not in options:
            return
        page += 1
