"""Write the definition into the target. Needs no source and no driver for one."""
import base64
import json
import os
from importlib.resources import files

import adbc_driver_postgresql.dbapi as adbc

from . import definition, seal, target


def apply(directory, key_file):
    sources, tables, digest = definition.read(directory, os.environ)
    try:
        public = seal.public_key(key_file)
    except OSError as e:
        raise SystemExit(f"public key {key_file}: {e.strerror}")
    except Exception:
        raise SystemExit(f"{key_file} holds no public key")
    for s in sources:
        s["connection"] = base64.b64encode(seal.seal(public, s["name"], s["connection"])).decode()
        s["key_id"] = seal.key_id(public)
    conn = target.connect()
    # a changed target name moves nothing: say so, so that no stale mirror is left behind unknowingly
    old = {(src, tbl): f"{schema}.{name}" for src, tbl, schema, name in target.sql(
        conn, "SELECT source, source_table, target_schema, target_table FROM _rowvioli.tables")}
    changed = []
    for t in tables:
        was, now = old.get((t["source"], t["source_table"])), f"{t['target_schema']}.{t['target_table']}"
        if was not in (None, now):
            changed.append(f"{t['source']}: {t['source_table']}: target name changes from {was} to {now}; the old "
                           f"tables ({was}, its __log and __history) stay where they are")
    payload = json.dumps({"sources": sources, "tables": tables, "definition": digest}, default=str)
    try:
        target.transaction(conn, files(__package__).joinpath("sql/apply.sql").read_text(), [payload])
    except adbc.Error as e:  # Postgres names what it refused, for example a time zone it does not know
        raise SystemExit(f"the target refused the definition, nothing was changed: {e}")
    print(*changed, sep="\n", end="\n" if changed else "")
    print(f"applied {len(sources)} sources with {len(tables)} tables")
