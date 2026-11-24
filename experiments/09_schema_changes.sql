-- Throwaway prototype for .scratch/schema-changes/strategy.md: does the design of schema changes work in PostgreSQL 16?
-- A mirror m, its change log m__log and its history view m__history are played by hand; one staging table per "run",
-- fixed timestamps per run. Every claim ends in a query that prints `ok` or `FAIL: <what>`; the script runs to the end.
\set ON_ERROR_STOP off
\pset tuples_only on
\pset format unaligned
SET timezone = 'UTC';
SET client_min_messages = warning;

-- ---------------------------------------------------------------- helpers
CREATE FUNCTION chk(ok boolean, what text) RETURNS text LANGUAGE sql AS
  $$ SELECT CASE WHEN coalesce(ok, false) THEN 'ok' ELSE 'FAIL: ' || what END $$;

-- runs a statement; says 'executed' or the error message
CREATE FUNCTION try(stmt text) RETURNS text LANGUAGE plpgsql AS
  $$ BEGIN EXECUTE stmt; RETURN 'executed'; EXCEPTION WHEN others THEN RETURN SQLERRM; END $$;

-- the current columns of a table, in order
CREATE FUNCTION cols(tbl text) RETURNS text LANGUAGE sql AS
  $$ SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) FROM pg_attribute
      WHERE attrelid = tbl::regclass AND attnum > 0 AND NOT attisdropped $$;

-- replay: the latest row image per key from the log alone, D left out, only the mirror's current columns.
-- pred restricts the log to a stretch of one key; the result is <tbl>__replay
CREATE FUNCTION replay(tbl text, key text[], pred text DEFAULT 'true') RETURNS void LANGUAGE plpgsql AS $$
DECLARE k text := (SELECT string_agg(quote_ident(x), ', ') FROM unnest(key) x);
BEGIN
  EXECUTE format('DROP TABLE IF EXISTS %s__replay', tbl);
  EXECUTE format($f$CREATE TABLE %1$s__replay AS SELECT %2$s FROM (
      SELECT DISTINCT ON (%3$s) _op, %2$s FROM %1$s__log WHERE %4$s ORDER BY %3$s, _loaded_at DESC, _run DESC) r
      WHERE _op <> 'D'$f$, tbl, cols(tbl), k, pred);
END $$;

-- the two tables hold the same rows, compared in both directions
CREATE FUNCTION same(a text, b text) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE r boolean;
BEGIN
  EXECUTE format('SELECT NOT EXISTS (SELECT * FROM %1$s EXCEPT SELECT * FROM %2$s)
                    AND NOT EXISTS (SELECT * FROM %2$s EXCEPT SELECT * FROM %1$s)
                    AND (SELECT count(*) FROM %1$s) = (SELECT count(*) FROM %2$s)', a, b) INTO r;
  RETURN r;
EXCEPTION WHEN others THEN RETURN false; END $$;

-- the history view as load.py writes it
CREATE FUNCTION mkhist(tbl text, key text[], drop_first boolean DEFAULT false) RETURNS void LANGUAGE plpgsql AS $$
DECLARE c text; k text := (SELECT string_agg(quote_ident(x), ', ') FROM unnest(key) x);
BEGIN
  SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO c FROM pg_attribute
   WHERE attrelid = (tbl || '__log')::regclass AND attnum > 0 AND NOT attisdropped
     AND attname NOT IN ('_run', '_op', '_loaded_at');
  IF drop_first THEN EXECUTE format('DROP VIEW IF EXISTS %s__history', tbl); END IF;
  EXECUTE format($f$CREATE OR REPLACE VIEW %1$s__history AS
      SELECT _valid_from, _valid_to, %2$s FROM (
        SELECT _op, _loaded_at AS _valid_from,
               lead(_loaded_at) OVER (PARTITION BY %3$s ORDER BY _loaded_at) AS _valid_to, %2$s
          FROM %1$s__log) h WHERE _op <> 'D'$f$, tbl, c, k);
END $$;

-- one run: diff of staging against the mirror over the MIRROR's columns (a column the staging lacks is NULL), the
-- diff into log and mirror. Column changes are made by the caller: a new column before, a dropped one after.
CREATE FUNCTION apply_run(tbl text, stg text, key text[], run int, ts timestamptz) RETURNS text LANGUAGE plpgsql AS $$
DECLARE c text; s text; m text; on_s text; on_d text; res text;
BEGIN
  SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum),
         string_agg(CASE WHEN EXISTS (SELECT 1 FROM pg_attribute q WHERE q.attrelid = stg::regclass
                                         AND q.attname = a.attname AND q.attnum > 0 AND NOT q.attisdropped)
                         THEN 's.' || quote_ident(attname) ELSE 'NULL::' || format_type(atttypid, atttypmod) END,
                    ', ' ORDER BY attnum),
         string_agg('m.' || quote_ident(attname), ', ' ORDER BY attnum)
    INTO c, s, m FROM pg_attribute a WHERE attrelid = tbl::regclass AND attnum > 0 AND NOT attisdropped;
  SELECT string_agg(format('s.%1$I = m.%1$I', x), ' AND '), string_agg(format('d.%1$I = m.%1$I', x), ' AND ')
    INTO on_s, on_d FROM unnest(key) x;
  DROP TABLE IF EXISTS _diff;
  EXECUTE format($f$CREATE TEMP TABLE _diff AS
      SELECT 'D'::text AS _op, %3$s FROM %1$s m WHERE NOT EXISTS (SELECT FROM %2$s s WHERE %5$s)
      UNION ALL
      SELECT CASE WHEN m.%6$I IS NULL THEN 'I' ELSE 'U' END, %4$s FROM %2$s s LEFT JOIN %1$s m ON %5$s
       WHERE m.%6$I IS NULL OR ROW(%4$s) IS DISTINCT FROM ROW(%3$s)$f$, tbl, stg, m, s, on_s, key[1]);
  EXECUTE format('INSERT INTO %1$s__log (_run, _op, _loaded_at, %2$s) SELECT %3$s, _op, %4$L, %2$s FROM _diff',
                 tbl, c, run, ts);
  EXECUTE format('DELETE FROM %1$s m USING _diff d WHERE d._op IN (''D'', ''U'') AND %2$s', tbl, on_d);
  EXECUTE format('INSERT INTO %1$s (%2$s) SELECT %2$s FROM _diff WHERE _op IN (''I'', ''U'')', tbl, c);
  SELECT string_agg(x._op || '=' || x.cnt, ' ' ORDER BY x._op) INTO res FROM (SELECT _op, count(*) AS cnt FROM _diff GROUP BY _op) x;
  RETURN coalesce(res, 'no rows');
END $$;

-- ---------------------------------------------------------------- P1
\echo == P1 a column goes (rule 3)
CREATE TABLE m (id int PRIMARY KEY, name text, city text);
INSERT INTO m VALUES (1, 'Anna', 'Berlin'), (2, 'Ben', 'Hamburg'), (3, 'Cy', NULL);
CREATE TABLE m__log (_run bigint, _op text, _loaded_at timestamptz, LIKE m);
INSERT INTO m__log SELECT 1, 'I', '2026-01-01 02:00+00', * FROM m;
SELECT mkhist('m', ARRAY['id']) \g /dev/null
CREATE TABLE st2 (id int, name text);   -- the source no longer has city
INSERT INTO st2 VALUES (1, 'Anna'), (2, 'Ben'), (3, 'Cy');
BEGIN;
SELECT 'run 2: ' || apply_run('m', 'st2', ARRAY['id'], 2, '2026-01-02 02:00+00');
ALTER TABLE m DROP COLUMN city;
COMMIT;
SELECT replay('m', ARRAY['id']) \g /dev/null
SELECT chk(same('m', 'm__replay'), 'P1 the log does not replay to the mirror');
SELECT chk(NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'm'::regclass AND attname = 'city' AND NOT attisdropped)
       AND EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'm__log'::regclass AND attname = 'city' AND NOT attisdropped),
       'P1 city should be gone from the mirror and kept in the log');
SELECT chk((SELECT count(*) FROM m__log WHERE _run = 2 AND _op = 'U') = 2
       AND NOT EXISTS (SELECT 1 FROM m__log WHERE _run = 2 AND id = 3)
       AND NOT EXISTS (SELECT 1 FROM m__log WHERE _run = 2 AND city IS NOT NULL),
       'P1 expected one U with city NULL for ids 1 and 2 and nothing for id 3 (city was NULL)');
SELECT chk(EXISTS (SELECT 1 FROM m__history WHERE id = 1 AND city = 'Berlin' AND _valid_to = '2026-01-02 02:00+00')
       AND EXISTS (SELECT 1 FROM m__history WHERE id = 1 AND city IS NULL AND _valid_to IS NULL)
       AND (SELECT count(*) FROM m__history WHERE id = 3) = 1,
       'P1 history should end the Berlin version at the drop and show a current one with NULL; id 3 has one version');

-- ---------------------------------------------------------------- P2
\echo == P2 the column comes back, same type (rule 2)
SELECT attnum AS city_attnum FROM pg_attribute WHERE attrelid = 'm__log'::regclass AND attname = 'city' \gset
CREATE TABLE st3 (id int, name text, city text);
INSERT INTO st3 VALUES (1, 'Anna', 'Berlin'), (2, 'Ben', 'Köln'), (3, 'Cy', NULL);
BEGIN;
ALTER TABLE m ADD COLUMN city text;      -- the log column continues, nothing to do there
SELECT 'run 3: ' || apply_run('m', 'st3', ARRAY['id'], 3, '2026-01-03 02:00+00');
COMMIT;
SELECT replay('m', ARRAY['id']) \g /dev/null
SELECT chk(same('m', 'm__replay'), 'P2 the log does not replay to the mirror');
SELECT chk((SELECT count(*) FROM m__log WHERE _run = 3 AND _op = 'U') = 2
       AND (SELECT attnum FROM pg_attribute WHERE attrelid = 'm__log'::regclass AND attname = 'city') = :city_attnum,
       'P2 expected one U per row with a value, and the same log column');
SELECT chk((SELECT string_agg(coalesce(city, '-'), ',' ORDER BY _valid_from) FROM m__history WHERE id = 1) = 'Berlin,-,Berlin',
       'P2 history of id 1 should read Berlin, -, Berlin');

-- ---------------------------------------------------------------- P3
\echo == P3 it comes back in another family, text to integer (rule 2, third row)
BEGIN;   -- run 4: city goes once more
SELECT 'run 4: ' || apply_run('m', 'st2', ARRAY['id'], 4, '2026-01-04 02:00+00');
ALTER TABLE m DROP COLUMN city;
COMMIT;
CREATE TABLE st5 (id int, name text, city integer);
INSERT INTO st5 VALUES (1, 'Anna', 10115), (2, 'Ben', 50667), (3, 'Cy', NULL);
BEGIN;   -- run 5: city is an integer now
ALTER TABLE m__log RENAME COLUMN city TO city__5;
ALTER TABLE m__log ADD COLUMN city integer;
ALTER TABLE m ADD COLUMN city integer;
SELECT 'run 5: ' || apply_run('m', 'st5', ARRAY['id'], 5, '2026-01-05 02:00+00');
COMMIT;
-- the old view survived the RENAME and serves the retired text values under the name city
SELECT 'note: old view after the change: city is ' || pg_typeof(city) || ', first value ' || min(city::text)
  FROM m__history WHERE id = 1 GROUP BY pg_typeof(city);
SELECT 'note: CREATE OR REPLACE (log order): ' || try($q$SELECT mkhist('m', ARRAY['id'])$q$);
SELECT 'note: CREATE OR REPLACE (city kept in place, city__5 appended): ' ||
  try($q$CREATE OR REPLACE VIEW m__history AS SELECT _valid_from, _valid_to, id, name, city, city__5 FROM (
         SELECT _op, _loaded_at AS _valid_from, lead(_loaded_at) OVER (PARTITION BY id ORDER BY _loaded_at) AS _valid_to,
                id, name, city, city__5 FROM m__log) h WHERE _op <> 'D'$q$);
SELECT chk(try($q$SELECT mkhist('m', ARRAY['id'])$q$) <> 'executed'
       AND try($q$CREATE OR REPLACE VIEW m__history AS SELECT _valid_from, _valid_to, id, name, city, city__5 FROM (
         SELECT _op, _loaded_at AS _valid_from, lead(_loaded_at) OVER (PARTITION BY id ORDER BY _loaded_at) AS _valid_to,
                id, name, city, city__5 FROM m__log) h WHERE _op <> 'D'$q$) <> 'executed',
       'P3 CREATE OR REPLACE VIEW was expected to fail');
SELECT chk((SELECT pg_typeof(city)::text FROM m__history LIMIT 1) = 'text',
       'P3 the old view was expected to keep serving the retired text column as city (it did not)');
-- DROP VIEW, CREATE VIEW:
SELECT mkhist('m', ARRAY['id'], true) \g /dev/null
SELECT chk((SELECT pg_typeof(city)::text FROM m__history LIMIT 1) = 'integer'
       AND (SELECT count(*) FROM information_schema.columns WHERE table_name = 'm__history' AND column_name IN ('city', 'city__5')) = 2,
       'P3 the recreated view should have city integer and city__5');
SELECT replay('m', ARRAY['id']) \g /dev/null
SELECT chk(same('m', 'm__replay'), 'P3 the log does not replay to the mirror');
SELECT chk((SELECT city__5 FROM m__history WHERE id = 1 AND _valid_from = '2026-01-01 02:00+00') = 'Berlin'
       AND (SELECT city FROM m__history WHERE id = 1 AND _valid_to IS NULL) = 10115,
       'P3 old text values should be readable as city__5, the current value as city');

-- ---------------------------------------------------------------- P4
\echo == P4 lazy widening (rule 4)
CREATE TABLE s4 (i_ok bigint, i_bad bigint, n_ok numeric(14,4), n_bad numeric(14,4), n_ovf numeric(16,4),
                 d_ok timestamp, d_bad timestamp, r_ok double precision, r_bad double precision, r_ovf double precision);
INSERT INTO s4 VALUES (1, 1, 1.5, 1.5, 1.5, '2026-01-01 00:00', '2026-01-01 00:00', 0.5, 0.5, 0.5),
                      (2, 3000000000, 2.25, 1.2345, 12345678901.5, '2026-01-02 00:00', '2026-01-02 12:00', 0.25, 0.1, 1e300);
-- does every staged value fit the target type: a round trip through the target type changes nothing; a cast that
-- fails (overflow) is a value that does not fit
CREATE FUNCTION fits(stg text, col text, target text) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE src text; r boolean;
BEGIN
  SELECT format_type(atttypid, atttypmod) INTO src FROM pg_attribute WHERE attrelid = stg::regclass AND attname = col;
  EXECUTE format('SELECT NOT EXISTS (SELECT 1 FROM %s WHERE %I IS DISTINCT FROM (%I::%s)::%s)', stg, col, col, target, src) INTO r;
  RETURN r;
EXCEPTION WHEN others THEN RETURN false; END $$;
SELECT chk(fits('s4','i_ok','integer') AND NOT fits('s4','i_bad','integer')
       AND fits('s4','n_ok','numeric(12,2)') AND NOT fits('s4','n_bad','numeric(12,2)') AND NOT fits('s4','n_ovf','numeric(12,2)')
       AND fits('s4','d_ok','date') AND NOT fits('s4','d_bad','date')
       AND fits('s4','r_ok','real') AND NOT fits('s4','r_bad','real') AND NOT fits('s4','r_ovf','real'),
       'P4 the round-trip test misjudged one of the 10 cases');
-- the type that holds both. exact numbers: integer types take the larger; with numeric, every integer type counts as
-- numeric(5|10|19, 0), digits before the point = max of both, digits after = max of both, precision = their sum
-- (more than 1000 would be plain numeric: not handled). date + timestamp = timestamp; real + double = double precision
CREATE FUNCTION numdims(t text) RETURNS int[] LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN t = 'smallint' THEN ARRAY[5,0] WHEN t = 'integer' THEN ARRAY[10,0] WHEN t = 'bigint' THEN ARRAY[19,0]
              WHEN t ~ '^numeric\(\d+,\d+\)$' THEN ARRAY[(regexp_match(t, '\((\d+),(\d+)\)'))[1]::int - (regexp_match(t, '\((\d+),(\d+)\)'))[2]::int,
                                                         (regexp_match(t, '\((\d+),(\d+)\)'))[2]::int] END $$;
CREATE FUNCTION wider(a text, b text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN a = b THEN a
    WHEN a IN ('smallint','integer','bigint') AND b IN ('smallint','integer','bigint')
      THEN CASE WHEN 'bigint' IN (a, b) THEN 'bigint' WHEN 'integer' IN (a, b) THEN 'integer' ELSE 'smallint' END
    WHEN (a ~ '^numeric' OR a IN ('smallint','integer','bigint')) AND (b ~ '^numeric' OR b IN ('smallint','integer','bigint'))
      THEN CASE WHEN a = 'numeric' OR b = 'numeric' THEN 'numeric'
                ELSE format('numeric(%s,%s)', greatest((numdims(a))[1], (numdims(b))[1]) + greatest((numdims(a))[2], (numdims(b))[2]),
                                              greatest((numdims(a))[2], (numdims(b))[2])) END
    WHEN a IN ('date','timestamp without time zone') AND b IN ('date','timestamp without time zone') THEN 'timestamp without time zone'
    WHEN a IN ('real','double precision') AND b IN ('real','double precision') THEN 'double precision'
  END $$;
SELECT chk(wider('integer','bigint') = 'bigint' AND wider('numeric(12,2)','numeric(14,4)') = 'numeric(14,4)'
       AND wider('numeric(12,2)','numeric(16,4)') = 'numeric(16,4)'
       AND wider('numeric(12,4)','numeric(14,2)') = 'numeric(16,4)'   -- 8 before + 4 after would lose digits: 12 before, 4 after
       AND wider('integer','numeric(12,2)') = 'numeric(12,2)' AND wider('bigint','numeric(12,2)') = 'numeric(21,2)'
       AND wider('date','timestamp without time zone') = 'timestamp without time zone'
       AND wider('real','double precision') = 'double precision' AND wider('text','integer') IS NULL,
       'P4 the rule for the type that holds both gave an unexpected type');
-- the run's step: for every column whose staged values do not fit, alter mirror and log
CREATE FUNCTION widen_cols(tbl text, stg text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE a record; cur text; src text; nt text; out text := '';
BEGIN
  FOR a IN SELECT attname FROM pg_attribute WHERE attrelid = tbl::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum LOOP
    SELECT format_type(atttypid, atttypmod) INTO src FROM pg_attribute WHERE attrelid = stg::regclass AND attname = a.attname AND NOT attisdropped;
    CONTINUE WHEN src IS NULL;
    SELECT format_type(atttypid, atttypmod) INTO cur FROM pg_attribute WHERE attrelid = tbl::regclass AND attname = a.attname;
    CONTINUE WHEN fits(stg, a.attname, cur);
    nt := wider(cur, src);
    IF nt IS NULL THEN RAISE EXCEPTION 'column %: % and % are of different families', a.attname, cur, src; END IF;
    EXECUTE format('ALTER TABLE %s ALTER COLUMN %I TYPE %s', tbl, a.attname, nt);
    EXECUTE format('ALTER TABLE %s__log ALTER COLUMN %I TYPE %s', tbl, a.attname, nt);
    out := out || format('%s %s->%s; ', a.attname, cur, nt);
  END LOOP;
  RETURN out;
END $$;
CREATE TABLE w (id int PRIMARY KEY, i integer, n numeric(12,2), d date, r real);
INSERT INTO w VALUES (1, 1, 1.50, '2026-01-01', 0.5);
CREATE TABLE w__log (_run bigint, _op text, _loaded_at timestamptz, LIKE w);
INSERT INTO w__log SELECT 1, 'I', '2026-01-01 02:00+00', * FROM w;
SELECT mkhist('w', ARRAY['id']) \g /dev/null
CREATE TABLE ws2 (id int, i bigint, n numeric(14,4), d timestamp, r double precision);
INSERT INTO ws2 VALUES (1, 3000000000, 1.2345, '2026-01-01 12:00', 0.1);
SELECT 'note: ALTER with the history view in place: ' || try($q$SELECT widen_cols('w', 'ws2')$q$);
SELECT chk(try($q$SELECT widen_cols('w', 'ws2')$q$) ~ 'used by a view', 'P4 ALTER TYPE of a log column was expected to be refused by the history view');
BEGIN;
DROP VIEW w__history;
SELECT 'widened: ' || widen_cols('w', 'ws2');
SELECT mkhist('w', ARRAY['id']) \g /dev/null
SELECT 'run 2: ' || apply_run('w', 'ws2', ARRAY['id'], 2, '2026-01-02 02:00+00');
COMMIT;
SELECT replay('w', ARRAY['id']) \g /dev/null
SELECT chk(same('w', 'w__replay')
       AND (SELECT string_agg(format_type(atttypid, atttypmod), ',' ORDER BY attnum) FROM pg_attribute
             WHERE attrelid = 'w'::regclass AND attnum > 1 AND NOT attisdropped) = 'bigint,numeric(14,4),timestamp without time zone,double precision'
       AND (SELECT string_agg(format_type(atttypid, atttypmod), ',' ORDER BY attnum) FROM pg_attribute
             WHERE attrelid = 'w__log'::regclass AND attnum > 4 AND NOT attisdropped) = 'bigint,numeric(14,4),timestamp without time zone,double precision'
       AND (SELECT i FROM w__history WHERE _valid_to IS NULL) = 3000000000
       AND (SELECT n FROM w__history WHERE _valid_to IS NOT NULL) = 1.5,
       'P4 widening of mirror and log (and the view) did not give the expected types or values');
-- a source that narrows changes nothing; another family is a different matter
SELECT chk(fits('ws2', 'i', 'bigint') AND wider('bigint', 'integer') = 'bigint', 'P4 narrowing source should fit the wide target');

-- ---------------------------------------------------------------- P5
\echo == P5 a key changes (id) to (id, tenant), tenant of id 7 changed in the old stretch (rule 5)
CREATE TABLE k (id int PRIMARY KEY, tenant text, v text);
INSERT INTO k VALUES (7, 'a', 'x'), (8, 'a', 'y');
CREATE TABLE k__log (_run bigint, _op text, _loaded_at timestamptz, LIKE k);
INSERT INTO k__log SELECT 1, 'I', '2026-01-01 02:00+00', * FROM k;
SELECT mkhist('k', ARRAY['id']) \g /dev/null
CREATE TABLE snap AS SELECT 1 AS moment, * FROM k;
CREATE TABLE ks2 (id int, tenant text, v text);
INSERT INTO ks2 VALUES (7, 'b', 'x'), (8, 'a', 'y');
SELECT 'run 2: ' || apply_run('k', 'ks2', ARRAY['id'], 2, '2026-01-02 02:00+00');
INSERT INTO snap SELECT 2, * FROM k;
CREATE TABLE ks3 (id int, tenant text, v text);
INSERT INTO ks3 VALUES (7, 'b', 'x'), (8, 'a', 'y2'), (9, 'a', 'z');
SELECT 'run 3: ' || apply_run('k', 'ks3', ARRAY['id'], 3, '2026-01-03 02:00+00');
INSERT INTO snap SELECT 3, * FROM k;
-- run 4, the seam: D for every old row, replace the mirror, new key, I for every new row
CREATE TABLE ks4 (id int, tenant text, v text);
INSERT INTO ks4 VALUES (7, 'b', 'x'), (8, 'a', 'y2'), (9, 'a', 'z'), (10, 'c', 'n');
BEGIN;
INSERT INTO k__log (_run, _op, _loaded_at, id, tenant, v) SELECT 4, 'D', '2026-01-04 02:00+00', id, tenant, v FROM k;
ALTER TABLE k DROP CONSTRAINT k_pkey;
DELETE FROM k;
INSERT INTO k SELECT * FROM ks4;
ALTER TABLE k ADD PRIMARY KEY (id, tenant);
INSERT INTO k__log (_run, _op, _loaded_at, id, tenant, v) SELECT 4, 'I', '2026-01-04 02:00+00', id, tenant, v FROM k;
-- the view: one branch per stretch. The seam run belongs to both: its D rows end the old stretch, its I rows begin the new
DROP VIEW k__history;
CREATE VIEW k__history AS
  SELECT _valid_from, _valid_to, id, tenant, v FROM (
    SELECT _op, _loaded_at AS _valid_from, lead(_loaded_at) OVER (PARTITION BY id ORDER BY _loaded_at) AS _valid_to, id, tenant, v
      FROM k__log WHERE _run < 4 OR (_run = 4 AND _op = 'D')) h WHERE _op <> 'D'
  UNION ALL
  SELECT _valid_from, _valid_to, id, tenant, v FROM (
    SELECT _op, _loaded_at AS _valid_from, lead(_loaded_at) OVER (PARTITION BY id, tenant ORDER BY _loaded_at) AS _valid_to, id, tenant, v
      FROM k__log WHERE _run > 4 OR (_run = 4 AND _op = 'I')) h WHERE _op <> 'D';
COMMIT;
INSERT INTO snap SELECT 4, * FROM k;
CREATE TABLE ks5 (id int, tenant text, v text);
INSERT INTO ks5 VALUES (7, 'b', 'x'), (8, 'a', 'y3'), (9, 'a', 'z'), (11, 'd', 'q');   -- (10,c) is deleted
SELECT 'run 5: ' || apply_run('k', 'ks5', ARRAY['id', 'tenant'], 5, '2026-01-05 02:00+00');
INSERT INTO snap SELECT 5, * FROM k;
-- the table as it was at a moment, compared with the snapshot of the mirror taken then
CREATE FUNCTION at_ok(vw text, mom timestamptz, sid int) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE r boolean;
BEGIN
  EXECUTE format($f$SELECT NOT EXISTS (SELECT id, tenant, v FROM %1$s WHERE _valid_from <= %2$L AND (_valid_to IS NULL OR %2$L < _valid_to)
                                      EXCEPT SELECT id, tenant, v FROM snap WHERE moment = %3$s)
                AND NOT EXISTS (SELECT id, tenant, v FROM snap WHERE moment = %3$s EXCEPT
                                SELECT id, tenant, v FROM %1$s WHERE _valid_from <= %2$L AND (_valid_to IS NULL OR %2$L < _valid_to))
                AND (SELECT count(*) FROM %1$s WHERE _valid_from <= %2$L AND (_valid_to IS NULL OR %2$L < _valid_to))
                  = (SELECT count(*) FROM snap WHERE moment = %3$s)$f$, vw, mom, sid) INTO r;
  RETURN r;
END $$;
SELECT chk(at_ok('k__history', '2026-01-01 14:00+00', 1), 'P5 branches: wrong table before the tenant change');
SELECT chk(at_ok('k__history', '2026-01-02 14:00+00', 2), 'P5 branches: wrong table after the tenant change');
SELECT chk(at_ok('k__history', '2026-01-03 14:00+00', 3), 'P5 branches: wrong table just before the seam');
SELECT chk(at_ok('k__history', '2026-01-04 14:00+00', 4), 'P5 branches: wrong table just after the seam');
SELECT chk(at_ok('k__history', '2026-01-05 14:00+00', 5), 'P5 branches: wrong table in the new stretch');
SELECT chk(at_ok('k__history', '2026-01-04 02:00+00', 4), 'P5 branches: wrong table exactly at the seam (old version ends, new begins)');
-- one branch over the whole log, partitioned by the new key
CREATE VIEW k__hist_single AS
  SELECT _valid_from, _valid_to, id, tenant, v FROM (
    SELECT _op, _loaded_at AS _valid_from, lead(_loaded_at) OVER (PARTITION BY id, tenant ORDER BY _loaded_at) AS _valid_to, id, tenant, v
      FROM k__log) h WHERE _op <> 'D';
SELECT 'note: single branch by (id, tenant) is wrong at moments: ' || coalesce(string_agg(mo::text, ','), 'none')
  FROM (VALUES (1, '2026-01-01 14:00+00'::timestamptz), (2, '2026-01-02 14:00+00'), (3, '2026-01-03 14:00+00'),
               (4, '2026-01-04 14:00+00'), (5, '2026-01-05 14:00+00')) v(mo, ts) WHERE NOT at_ok('k__hist_single', ts, mo);
SELECT chk(NOT at_ok('k__hist_single', '2026-01-02 14:00+00', 2), 'P5 the single branch was expected to be wrong after the tenant change, and was not');
-- replay: with the new key it replays the new stretch only; over the whole log (7,a) of the old stretch survives
SELECT replay('k', ARRAY['id', 'tenant'], '_run > 4 OR (_run = 4 AND _op = ''I'')') \g /dev/null
SELECT chk(same('k', 'k__replay'), 'P5 the new stretch does not replay to the mirror');
SELECT replay('k', ARRAY['id', 'tenant']) \g /dev/null
SELECT chk(NOT same('k', 'k__replay'), 'P5 replay over the whole log with the new key was expected to be wrong, and was not');

-- ---------------------------------------------------------------- P6
\echo == P6 a first key (rule 5)
CREATE TABLE e (a int, b text);
INSERT INTO e VALUES (1, 'x'), (1, 'x'), (2, 'y');   -- no key, duplicates
SELECT 'note: PRIMARY KEY on the old mirror: ' || try('ALTER TABLE e ADD PRIMARY KEY (a)');
CREATE TABLE es (a int, b text);
INSERT INTO es VALUES (1, 'x'), (2, 'y'), (3, 'z');
BEGIN;
DELETE FROM e;
INSERT INTO e SELECT * FROM es;
ALTER TABLE e ADD PRIMARY KEY (a);
CREATE TABLE e__log (_run bigint, _op text, _loaded_at timestamptz, LIKE e);
INSERT INTO e__log SELECT 1, 'I', '2026-03-01 02:00+00', * FROM e;
COMMIT;
SELECT mkhist('e', ARRAY['a']) \g /dev/null
SELECT replay('e', ARRAY['a']) \g /dev/null
SELECT chk(try('ALTER TABLE es ADD PRIMARY KEY (a)') = 'executed' AND same('e', 'e__replay')
       AND (SELECT count(*) FROM e__log WHERE _op = 'I') = 3 AND (SELECT count(*) FROM e__history WHERE _valid_to IS NULL) = 3,
       'P6 replacing the mirror and adding the key should give a log that begins with every row');
CREATE TABLE f (id int PRIMARY KEY, code text);
ALTER TABLE f DROP CONSTRAINT f_pkey;
SELECT chk((SELECT attnotnull FROM pg_attribute WHERE attrelid = 'f'::regclass AND attname = 'id'), 'P6 NOT NULL was expected to stay behind');
SELECT 'note: the statement: ALTER TABLE f ALTER COLUMN id DROP NOT NULL';
ALTER TABLE f ALTER COLUMN id DROP NOT NULL;
SELECT chk(NOT (SELECT attnotnull FROM pg_attribute WHERE attrelid = 'f'::regclass AND attname = 'id'), 'P6 DROP NOT NULL did not remove it');
CREATE TABLE f2 (id int PRIMARY KEY, code text);
SELECT 'note: DROP NOT NULL while the primary key exists: ' || try('ALTER TABLE f2 ALTER COLUMN id DROP NOT NULL');
-- only the old key columns that are not in the new key lose it: rule 5's "dropping the NOT NULL" is per column

-- ---------------------------------------------------------------- P7
\echo == P7 rename proof (rule 6)
-- THE query: mirror (old column) and staging (new column) on the key; the rows that did not change otherwise
-- (every shared column but the two) are counted, how many of them have old = new, how many distinct values
CREATE FUNCTION proof(mt text, stg text, key text[], oldc text, newc text)
  RETURNS TABLE (n bigint, eq bigint, d bigint, proven boolean) LANGUAGE plpgsql AS $$
DECLARE rest text[]; ms text; ss text; j text;
BEGIN
  SELECT array_agg(a.attname::text ORDER BY a.attnum) INTO rest FROM pg_attribute a
    JOIN pg_attribute b ON b.attrelid = stg::regclass AND b.attname = a.attname AND b.attnum > 0 AND NOT b.attisdropped
   WHERE a.attrelid = mt::regclass AND a.attnum > 0 AND NOT a.attisdropped AND a.attname::text <> ALL (ARRAY[oldc, newc]);
  SELECT string_agg('m.' || quote_ident(x), ', '), string_agg('s.' || quote_ident(x), ', ') INTO ms, ss FROM unnest(rest) x;
  SELECT string_agg(format('s.%1$I = m.%1$I', x), ' AND ') INTO j FROM unnest(key) x;
  RETURN QUERY EXECUTE format($f$
    SELECT count(*), count(*) FILTER (WHERE m.%1$I IS NOT DISTINCT FROM s.%2$I), count(DISTINCT m.%1$I),
           count(*) > 0 AND count(*) = count(*) FILTER (WHERE m.%1$I IS NOT DISTINCT FROM s.%2$I) AND count(DISTINCT m.%1$I) > 1
      FROM %3$s m JOIN %4$s s ON %5$s
     WHERE ROW(%6$s) IS NOT DISTINCT FROM ROW(%7$s)$f$, oldc, newc, mt, stg, j, ms, ss);
END $$;
CREATE TABLE r (id int PRIMARY KEY, nick text, other text);
INSERT INTO r VALUES (1, 'ann', 'a'), (2, 'ben', 'b'), (3, 'cy', 'c'), (4, 'dee', 'd'), (5, 'eve', 'e');
CREATE TABLE r__log (_run bigint, _op text, _loaded_at timestamptz, LIKE r);
INSERT INTO r__log SELECT 1, 'I', '2026-01-01 02:00+00', * FROM r;
SELECT mkhist('r', ARRAY['id']) \g /dev/null
CREATE TABLE rs (id int, alias text, other text);     -- row 4 changed otherwise, and its alias differs: it is ignored
INSERT INTO rs VALUES (1, 'ann', 'a'), (2, 'ben', 'b'), (3, 'cy', 'c'), (4, 'DEE', 'd2'), (5, 'eve', 'e');
SELECT 'note: true rename: n=' || n || ' equal=' || eq || ' distinct=' || d || ' proven=' || proven FROM proof('r', 'rs', ARRAY['id'], 'nick', 'alias');
SELECT chk((SELECT n = 4 AND eq = 4 AND d = 4 AND proven FROM proof('r', 'rs', ARRAY['id'], 'nick', 'alias')),
       'P7 a true rename (with one row changed otherwise) was expected to be proven over 4 rows');
CREATE TABLE rf (id int PRIMARY KEY, flag_old boolean);
INSERT INTO rf VALUES (1, false), (2, false), (3, false), (4, false);
CREATE TABLE rfs (id int, flag_new boolean);
INSERT INTO rfs VALUES (1, false), (2, false), (3, false), (4, false);
SELECT 'note: two all-false flags: n=' || n || ' equal=' || eq || ' distinct=' || d || ' proven=' || proven FROM proof('rf', 'rfs', ARRAY['id'], 'flag_old', 'flag_new');
SELECT chk((SELECT NOT proven FROM proof('rf', 'rfs', ARRAY['id'], 'flag_old', 'flag_new')), 'P7 two all-false flags were proven');
CREATE TABLE ro (id int PRIMARY KEY, o text);
INSERT INTO ro VALUES (1, 'v');
CREATE TABLE ros (id int, n text);
INSERT INTO ros VALUES (1, 'v');
SELECT chk((SELECT NOT proven AND n = 1 FROM proof('ro', 'ros', ARRAY['id'], 'o', 'n')), 'P7 a one-row table was proven');
-- every row changed otherwise: no evidence at all
CREATE TABLE rs_all (id int, alias text, other text);
INSERT INTO rs_all VALUES (1, 'x', 'a2'), (2, 'y', 'b2'), (3, 'z', 'c2'), (4, 'w', 'd2'), (5, 'v', 'e2');
SELECT chk((SELECT NOT proven AND n = 0 FROM proof('r', 'rs_all', ARRAY['id'], 'nick', 'alias')), 'P7 no unchanged row, and still proven');
-- one unchanged row that differs: not a rename
CREATE TABLE rs_bad (id int, alias text, other text);
INSERT INTO rs_bad VALUES (1, 'ann', 'a'), (2, 'ben', 'b'), (3, 'CY', 'c'), (4, 'dee', 'd'), (5, 'eve', 'e');
SELECT chk((SELECT NOT proven AND eq = 4 AND n = 5 FROM proof('r', 'rs_bad', ARRAY['id'], 'nick', 'alias')), 'P7 a differing unchanged row did not stop the proof');
-- two new columns that both match: ambiguous
CREATE TABLE rs2 (id int, alias text, alias2 text, other text);
INSERT INTO rs2 VALUES (1, 'ann', 'ann', 'a'), (2, 'ben', 'ben', 'b'), (3, 'cy', 'cy', 'c'), (4, 'dee', 'dee', 'd'), (5, 'eve', 'eve', 'e');
SELECT chk((SELECT count(*) FROM (SELECT * FROM proof('r', 'rs2', ARRAY['id'], 'nick', 'alias')
                                  UNION ALL SELECT * FROM proof('r', 'rs2', ARRAY['id'], 'nick', 'alias2')) x WHERE proven) = 2,
       'P7 two matching new columns were expected to be both proven (so the rule must say: exactly one)');
-- the weak point: two rows with two values are proven too
CREATE TABLE rt (id int PRIMARY KEY, o text);
INSERT INTO rt VALUES (1, 'p'), (2, 'q');
CREATE TABLE rts (id int, n text);
INSERT INTO rts VALUES (1, 'p'), (2, 'q');
SELECT 'note: two rows, two values: proven=' || proven || ' (the threshold distinct > 1 is weak on small tables)' FROM proof('rt', 'rts', ARRAY['id'], 'o', 'n');
-- the rename itself
SELECT count(*) AS log_before FROM r__log \gset
BEGIN;
ALTER TABLE r RENAME COLUMN nick TO alias;
ALTER TABLE r__log RENAME COLUMN nick TO alias;
COMMIT;
SELECT 'note: CREATE OR REPLACE after the rename: ' || try($q$SELECT mkhist('r', ARRAY['id'])$q$);
SELECT chk(try($q$SELECT mkhist('r', ARRAY['id'])$q$) <> 'executed'
       AND (SELECT count(*) FROM information_schema.columns WHERE table_name = 'r__history' AND column_name = 'nick') = 1,
       'P7 CREATE OR REPLACE was expected to fail and the old view to keep the old name nick');
SELECT mkhist('r', ARRAY['id'], true) \g /dev/null
SELECT replay('r', ARRAY['id']) \g /dev/null
SELECT chk(same('r', 'r__replay') AND (SELECT count(*) FROM r__log) = :log_before
       AND (SELECT alias FROM r__history WHERE id = 1) = 'ann',
       'P7 after the rename the log should replay to the mirror with no row written');
SELECT 'run 2: ' || apply_run('r', 'rs', ARRAY['id'], 2, '2026-01-02 02:00+00');
SELECT replay('r', ARRAY['id']) \g /dev/null
SELECT chk((SELECT count(*) FROM r__log) = :log_before + 1 AND same('r', 'r__replay'), 'P7 the run after the rename should write only the row that changed otherwise');

-- ---------------------------------------------------------------- P8
\echo == P8 locks (rule 9)
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE FUNCTION p8_held(stmt text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE r text;
BEGIN
  SET LOCAL lock_timeout = '2s';
  EXECUTE stmt;
  SELECT string_agg(relation::regclass::text, ',' ORDER BY relation::regclass::text) INTO r FROM pg_locks
   WHERE pid = pg_backend_pid() AND mode = 'AccessExclusiveLock' AND locktype = 'relation'
     AND relation IN ('m'::regclass, 'm__log'::regclass, 'm__history'::regclass);
  RETURN r;
END $$;
SELECT chk(p8_held('LOCK TABLE m, m__log, m__history IN ACCESS EXCLUSIVE MODE') = 'm,m__history,m__log',
       'P8 LOCK TABLE with a view was expected to hold all three');
SELECT 'note: LOCK TABLE m__history alone holds: ' || p8_held('LOCK TABLE m__history IN ACCESS EXCLUSIVE MODE') || ' (a view locks the tables it reads)';
-- the order Postgres takes them: a second session holds m__log; the locker asks for the list; pg_locks says
-- which it holds and which it waits for
CREATE FUNCTION lock_order(lst text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE p int; r text; c text := 'host=127.0.0.1 user=postgres password=x dbname=postgres';
BEGIN
  PERFORM dblink_connect('blk', c); PERFORM dblink_connect('lk', c);
  PERFORM dblink_exec('blk', 'BEGIN'); PERFORM dblink_exec('blk', 'LOCK TABLE m__log IN ACCESS EXCLUSIVE MODE');
  PERFORM dblink_exec('lk', 'BEGIN'); PERFORM dblink_exec('lk', 'SET LOCAL lock_timeout = ''20s''');
  SELECT pid INTO p FROM dblink('lk', 'SELECT pg_backend_pid()') AS t(pid int);
  PERFORM dblink_send_query('lk', 'LOCK TABLE ' || lst || ' IN ACCESS EXCLUSIVE MODE');
  PERFORM pg_sleep(1);
  SELECT coalesce(string_agg(relation::regclass::text || '=' || CASE WHEN granted THEN 'granted' ELSE 'WAITING' END, ' '
                             ORDER BY relation::regclass::text), 'none') INTO r FROM pg_locks
   WHERE pid = p AND locktype = 'relation' AND relation IN ('m'::regclass, 'm__log'::regclass, 'm__history'::regclass);
  PERFORM dblink_cancel_query('lk'); PERFORM dblink_exec('blk', 'ROLLBACK');
  PERFORM dblink_disconnect('lk'); PERFORM dblink_disconnect('blk');
  RETURN r;
EXCEPTION WHEN others THEN
  r := 'error: ' || SQLERRM;
  PERFORM try($t$SELECT dblink_disconnect('lk')$t$); PERFORM try($t$SELECT dblink_disconnect('blk')$t$);
  RETURN r;
END $$;
SELECT 'note: written m, m__log, m__history; m__log is held elsewhere: ' || lock_order('m, m__log, m__history');
SELECT 'note: written m__history, m__log, m; m__log is held elsewhere: ' || lock_order('m__history, m__log, m');
SELECT chk(lock_order('m, m__log, m__history') = 'm=granted m__log=WAITING', 'P8 order as written: m granted, m__log waited for, m__history not yet asked');
SELECT chk(lock_order('m__history, m__log, m') = 'm__history=granted m__log=WAITING', 'P8 reversed list: view first, then its table m__log, m not yet');
-- lock_timeout: the statement fails as a whole and holds nothing afterwards
CREATE FUNCTION lock_timeout_test() RETURNS text LANGUAGE plpgsql AS $$
DECLARE p int; msg text; held int; c text := 'host=127.0.0.1 user=postgres password=x dbname=postgres';
BEGIN
  PERFORM dblink_connect('blk', c); PERFORM dblink_connect('lk', c);
  PERFORM dblink_exec('blk', 'BEGIN'); PERFORM dblink_exec('blk', 'LOCK TABLE m__log IN ACCESS EXCLUSIVE MODE');
  PERFORM dblink_exec('lk', 'BEGIN'); PERFORM dblink_exec('lk', 'SET LOCAL lock_timeout = ''300ms''');
  SELECT pid INTO p FROM dblink('lk', 'SELECT pg_backend_pid()') AS t(pid int);
  msg := try($t$SELECT dblink_exec('lk', 'LOCK TABLE m, m__log, m__history IN ACCESS EXCLUSIVE MODE')$t$);
  PERFORM dblink_exec('lk', 'ROLLBACK');
  SELECT count(*) INTO held FROM pg_locks WHERE pid = p AND locktype = 'relation' AND mode = 'AccessExclusiveLock';
  PERFORM dblink_exec('blk', 'ROLLBACK'); PERFORM dblink_disconnect('lk'); PERFORM dblink_disconnect('blk');
  RETURN msg || ' / locks held after rollback: ' || held;
EXCEPTION WHEN others THEN
  PERFORM try($t$SELECT dblink_disconnect('lk')$t$); PERFORM try($t$SELECT dblink_disconnect('blk')$t$);
  RETURN 'error: ' || SQLERRM;
END $$;
SELECT 'note: ' || lock_timeout_test();
SELECT chk(lock_timeout_test() ~ 'lock timeout.*held after rollback: 0', 'P8 lock_timeout was expected to fail the statement and leave nothing held');

-- ---------------------------------------------------------------- P9
\echo == P9 pg_notify only on commit
SELECT dblink_connect('ls', 'host=127.0.0.1 user=postgres password=x dbname=postgres') \g /dev/null
SELECT dblink_exec('ls', 'LISTEN rowvioli_schema') \g /dev/null
BEGIN;
SELECT pg_notify('rowvioli_schema', 'rolled back') \g /dev/null
ROLLBACK;
SELECT pg_sleep(0.3) \g /dev/null
SELECT count(*) AS n_rollback FROM dblink_get_notify('ls') \gset
BEGIN;
SELECT pg_notify('rowvioli_schema', 'then an error') \g /dev/null
SELECT 1 / 0 \g /dev/null
ROLLBACK;
SELECT pg_sleep(0.3) \g /dev/null
SELECT count(*) AS n_error FROM dblink_get_notify('ls') \gset
BEGIN;
SELECT pg_notify('rowvioli_schema', 'committed') \g /dev/null
SELECT pg_sleep(0.3) \g /dev/null
SELECT count(*) AS n_before_commit FROM dblink_get_notify('ls') \gset
COMMIT;
SELECT pg_sleep(0.3) \g /dev/null
SELECT count(*) AS n_commit FROM dblink_get_notify('ls') \gset
SELECT count(*) AS n_again FROM dblink_get_notify('ls') \gset
SELECT chk(:n_rollback = 0 AND :n_error = 0 AND :n_before_commit = 0 AND :n_commit = 1 AND :n_again = 0,
       format('P9 delivered after rollback %s, after error %s, before commit %s, on commit %s, again %s (expected 0 0 0 1 0)',
              :n_rollback, :n_error, :n_before_commit, :n_commit, :n_again));
SELECT dblink_disconnect('ls') \g /dev/null

-- ---------------------------------------------------------------- P10
\echo == P10 the ledger (rule 7)
CREATE SCHEMA _rowvioli;
CREATE TABLE _rowvioli.columns (target_schema text, target_table text, "column" text, type text, source_type text,
  "key" int, mirror boolean, was text, "by" text, note text, PRIMARY KEY (target_schema, target_table, "column"));
CREATE TABLE _rowvioli.columns__log (_run bigint, _op text, _loaded_at timestamptz, LIKE _rowvioli.columns);
SELECT mkhist('_rowvioli.columns', ARRAY['target_schema', 'target_table', 'column']) \g /dev/null
CREATE FUNCTION led(run int, ts timestamptz, op text, col text, typ text, k int, mir boolean, was_ text DEFAULT NULL, nt text DEFAULT NULL)
  RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF op = 'D' THEN
    INSERT INTO _rowvioli.columns__log SELECT run, 'D', ts, * FROM _rowvioli.columns WHERE target_table = 'm' AND "column" = col;
    DELETE FROM _rowvioli.columns WHERE target_table = 'm' AND "column" = col;
  ELSE
    INSERT INTO _rowvioli.columns__log VALUES (run, op, ts, 'public', 'm', col, typ, typ, k, mir, was_, 'source', nt);
    INSERT INTO _rowvioli.columns VALUES ('public', 'm', col, typ, typ, k, mir, was_, 'source', nt)
      ON CONFLICT (target_schema, target_table, "column") DO UPDATE SET type = EXCLUDED.type, source_type = EXCLUDED.source_type,
        "key" = EXCLUDED."key", mirror = EXCLUDED.mirror, was = EXCLUDED.was, "by" = EXCLUDED."by", note = EXCLUDED.note;
  END IF;
END $$;
-- run 1: the table is new (m with id, name, city, tenant)
SELECT led(1, '2026-02-01 02:00+00', 'I', 'id', 'integer', 1, true) \g /dev/null
SELECT led(1, '2026-02-01 02:00+00', 'I', 'name', 'text', NULL, true) \g /dev/null
SELECT led(1, '2026-02-01 02:00+00', 'I', 'city', 'text', NULL, true) \g /dev/null
SELECT led(1, '2026-02-01 02:00+00', 'I', 'tenant', 'text', NULL, true) \g /dev/null
-- P1: run 2, city goes
SELECT led(2, '2026-02-02 02:00+00', 'U', 'city', 'text', NULL, false) \g /dev/null
-- P2: run 3, it comes back
SELECT led(3, '2026-02-03 02:00+00', 'U', 'city', 'text', NULL, true) \g /dev/null
-- P3: run 4 it goes, run 5 it comes back as integer; the old text column lives on in the log as city__5
SELECT led(4, '2026-02-04 02:00+00', 'U', 'city', 'text', NULL, false) \g /dev/null
SELECT led(5, '2026-02-05 02:00+00', 'I', 'city__5', 'text', NULL, false, 'city', 'retired by a change of type') \g /dev/null
SELECT led(5, '2026-02-05 02:00+00', 'U', 'city', 'integer', NULL, true) \g /dev/null
-- P7: run 6, name is renamed full_name
SELECT led(6, '2026-02-06 02:00+00', 'D', 'name', NULL, NULL, NULL) \g /dev/null
SELECT led(6, '2026-02-06 02:00+00', 'I', 'full_name', 'text', NULL, true, 'name', 'rename proven by the data') \g /dev/null
-- P5: run 7, the key becomes (id, tenant)
SELECT led(7, '2026-02-07 02:00+00', 'U', 'tenant', 'text', 2, true) \g /dev/null
CREATE FUNCTION ledger_at(mom timestamptz, only_mirror boolean) RETURNS text LANGUAGE sql AS $$
  SELECT string_agg("column" || ':' || type, ',' ORDER BY "column") FROM _rowvioli.columns__history
   WHERE target_table = 'm' AND _valid_from <= mom AND (_valid_to IS NULL OR mom < _valid_to) AND (mirror OR NOT only_mirror) $$;
CREATE FUNCTION ledger_key_at(mom timestamptz) RETURNS text LANGUAGE sql AS $$
  SELECT string_agg("column", ',' ORDER BY "key") FROM _rowvioli.columns__history
   WHERE target_table = 'm' AND "key" IS NOT NULL AND _valid_from <= mom AND (_valid_to IS NULL OR mom < _valid_to) $$;
SELECT chk(ledger_at('2026-02-01 14:00+00', true) = 'city:text,id:integer,name:text,tenant:text', 'P10 phase 1: ' || ledger_at('2026-02-01 14:00+00', true));
SELECT chk(ledger_at('2026-02-02 14:00+00', true) = 'id:integer,name:text,tenant:text', 'P10 phase P1 (city gone): ' || ledger_at('2026-02-02 14:00+00', true));
SELECT chk(ledger_at('2026-02-03 14:00+00', true) = 'city:text,id:integer,name:text,tenant:text', 'P10 phase P2 (city back): ' || ledger_at('2026-02-03 14:00+00', true));
SELECT chk(ledger_at('2026-02-05 14:00+00', true) = 'city:integer,id:integer,name:text,tenant:text'
       AND ledger_at('2026-02-05 14:00+00', false) = 'city:integer,city__5:text,id:integer,name:text,tenant:text',
       'P10 phase P3 (city integer, city__5 in the log only): ' || ledger_at('2026-02-05 14:00+00', false));
SELECT chk(ledger_at('2026-02-04 14:00+00', false) = 'city:text,id:integer,name:text,tenant:text',
       'P10 before the change of type the log column was still named city: ' || ledger_at('2026-02-04 14:00+00', false));
SELECT chk(ledger_at('2026-02-06 14:00+00', true) = 'city:integer,full_name:text,id:integer,tenant:text', 'P10 phase P7 (rename): ' || ledger_at('2026-02-06 14:00+00', true));
SELECT chk(ledger_key_at('2026-02-06 14:00+00') = 'id' AND ledger_key_at('2026-02-07 14:00+00') = 'id,tenant',
       'P10 phase P5 (key): ' || ledger_key_at('2026-02-06 14:00+00') || ' / ' || ledger_key_at('2026-02-07 14:00+00'));
SELECT replay('_rowvioli.columns', ARRAY['target_schema', 'target_table', 'column']) \g /dev/null
SELECT chk(same('_rowvioli.columns', '_rowvioli.columns__replay'), 'P10 the ledger log does not replay to the ledger');
SELECT 'note: the history of "city": ' || string_agg(type || '/' || mirror || '@' || to_char(_valid_from, 'DD') || '-' || coalesce(to_char(_valid_to, 'DD'), 'now'), '  ' ORDER BY _valid_from)
  FROM _rowvioli.columns__history WHERE "column" = 'city';
SELECT 'note: "name" ends at ' || to_char(max(_valid_to), 'DD') || ', full_name was=' || (SELECT was FROM _rowvioli.columns WHERE "column" = 'full_name')
  FROM _rowvioli.columns__history WHERE "column" = 'name';
