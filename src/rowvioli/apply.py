"""Write the definition into the target. Needs no source and no driver for one."""
import base64
import json
import os
from importlib.resources import files

import adbc_driver_postgresql.dbapi as adbc

from . import definition, seal, target, work


def apply(directory, key_file, init=False):
    sources, tables, digest = definition.read(directory, os.environ)
    try:
        public = seal.public_key(key_file)
    except OSError as e:
        raise SystemExit(f"public key {key_file}: {e.strerror}; `rowvioli key new` creates it")
    except Exception:
        raise SystemExit(f"{key_file} holds no public key")
    for s in sources:
        s["connection"] = base64.b64encode(seal.seal(public, s["name"], s["connection"])).decode()
        s["key_id"] = seal.key_id(public)
    try:
        conn = target.connect()
    except SystemExit as e:
        if not init or e.code != target.NO_SCHEMA:
            raise
        conn = target.connect(init=True)
        print("the schema _rowvioli is ready in the target")
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
        raise SystemExit("the target refused the definition, nothing was changed: "
                         + "\n".join(map(work.plain, str(e).split("\n"))))  # it may quote a value of the definition
    print(*map(work.plain, changed), sep="\n", end="\n" if changed else "")  # an old name may hold a control character
    print(f"applied {len(sources)} sources with {len(tables)} tables")
