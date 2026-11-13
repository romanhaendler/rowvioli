-- `apply`, in one transaction. The whole definition is the one jsonb parameter $1 of every statement.
-- Only the definition's columns are written: what the workers experienced is never touched.

-- A time zone this Postgres does not know raises here: on a row it would fail the status view for every table.
SELECT DISTINCT now() AT TIME ZONE timezone FROM jsonb_to_recordset($1::jsonb -> 'tables') AS x(timezone text);

INSERT INTO _rowvioli.sources AS s (name, type, parallel, options, connection, key_id, enabled)
SELECT name, type, parallel, options, decode(connection, 'base64'), key_id, true
  FROM jsonb_to_recordset($1::jsonb -> 'sources') AS x(name text, type text, parallel int,
                                                      options jsonb, connection text, key_id text)
    ON CONFLICT (name) DO UPDATE SET type = excluded.type,
       parallel = excluded.parallel, options = excluded.options, connection = excluded.connection,
       key_id = excluded.key_id, enabled = true;

UPDATE _rowvioli.sources SET enabled = false
 WHERE name NOT IN (SELECT x ->> 'name' FROM jsonb_array_elements($1::jsonb -> 'sources') x);

INSERT INTO _rowvioli.tables AS t (source, source_table, target_schema, target_table, key, max_age, at, timezone,
                                   log, max_delete_share, max_seconds, options, enabled)
SELECT source, source_table, target_schema, target_table, key, max_age::interval, at, timezone, log, max_delete_share,
       max_seconds, options, true
  FROM jsonb_to_recordset($1::jsonb -> 'tables') AS x(source text, source_table text, target_schema text,
                                                     target_table text, key text[], max_age text, at time[],
                                                     timezone text, log boolean, max_delete_share numeric,
                                                     max_seconds int, options jsonb)
    ON CONFLICT (source, source_table) DO UPDATE SET target_schema = excluded.target_schema,
       target_table = excluded.target_table, key = excluded.key,
       max_age = excluded.max_age, at = excluded.at, timezone = excluded.timezone, log = excluded.log,
       max_delete_share = excluded.max_delete_share, max_seconds = excluded.max_seconds, options = excluded.options,
       enabled = true;

UPDATE _rowvioli.tables SET enabled = false
 WHERE (source, source_table) NOT IN (SELECT x ->> 'source', x ->> 'source_table'
                                        FROM jsonb_array_elements($1::jsonb -> 'tables') x);

UPDATE _rowvioli.meta SET definition = $1::jsonb ->> 'definition';
