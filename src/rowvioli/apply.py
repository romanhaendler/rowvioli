"""Writing a definition into the target (spec "apply"). Needs no source and no driver for one."""
import base64
import json

from . import definition, seal
from .control import sql

# Each statement gets the whole definition as one jsonb parameter, so no driver-specific binding of arrays or bytea.
# Only definition columns are written; what the workers experienced is never touched.
STATEMENTS = [
    """INSERT INTO _rowvioli.sources AS s
           (name, type, target_schema, parallel, max_delete_share, max_seconds, connection, key_id, enabled)
       SELECT name, type, target_schema, coalesce(parallel, 2), coalesce(max_delete_share, 0.5),
              coalesce(max_seconds, 3600), decode(connection, 'base64'), key_id, true
         FROM jsonb_to_recordset($1::jsonb -> 'sources') AS x(name text, type text, target_schema text,
              parallel int, max_delete_share numeric, max_seconds int, connection text, key_id text)
       ON CONFLICT (name) DO UPDATE SET type = excluded.type, target_schema = excluded.target_schema,
              parallel = excluded.parallel, max_delete_share = excluded.max_delete_share,
              max_seconds = excluded.max_seconds, connection = excluded.connection,
              key_id = excluded.key_id, enabled = true""",
    """UPDATE _rowvioli.sources SET enabled = false
        WHERE name NOT IN (SELECT x->>'name' FROM jsonb_array_elements($1::jsonb -> 'sources') x)""",
    """INSERT INTO _rowvioli.tables AS t (source, source_table, target_table, key, max_age, enabled)
       SELECT source, source_table, target_table, key, max_age::interval, true
         FROM jsonb_to_recordset($1::jsonb -> 'tables')
              AS x(source text, source_table text, target_table text, key text[], max_age text)
       ON CONFLICT (source, source_table) DO UPDATE SET target_table = excluded.target_table,
              key = excluded.key, max_age = excluded.max_age, enabled = true""",
    """UPDATE _rowvioli.tables SET enabled = false
        WHERE (source, source_table) NOT IN (SELECT x->>'source', x->>'source_table'
                                               FROM jsonb_array_elements($1::jsonb -> 'tables') x)""",
]


def apply(conn, directory, public_key_file):
    sources, tables = definition.read(directory)
    pub = seal.load_public(public_key_file)
    for s in sources:
        s["connection"] = base64.b64encode(seal.seal(pub, s["name"], s["connection"])).decode()
        s["key_id"] = seal.key_id(pub)
    payload = json.dumps({"sources": sources, "tables": tables})
    sql(conn, "BEGIN")
    try:
        for s in STATEMENTS:
            sql(conn, s, [payload])
        sql(conn, "COMMIT")
    except Exception:
        sql(conn, "ROLLBACK")
        raise
