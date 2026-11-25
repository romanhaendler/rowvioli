\set VERBOSITY default
\pset tuples_only on
\pset format unaligned
SET client_min_messages = warning;
CREATE ROLE consumer;
CREATE TABLE m (id integer PRIMARY KEY, name text, city text, amount numeric(12,2), n integer, v varchar(10), ts timestamp, a integer, b integer);
INSERT INTO m SELECT g, 'n'||g, 'c'||g, g, g, 'v', now(), g, g FROM generate_series(1,1000) g;

\echo == 1 view blocks DROP COLUMN
CREATE VIEW v_city AS SELECT id, city FROM m;
ALTER TABLE m DROP COLUMN city;
\echo == 2 view blocks ALTER TYPE
ALTER TABLE m ALTER city TYPE varchar(50);
\echo == 3 rename: view survives, keeps old output name
ALTER TABLE m RENAME COLUMN city TO town;
SELECT string_agg(attname, ',') FROM pg_attribute WHERE attrelid = 'v_city'::regclass AND attnum > 0;
SELECT count(*) FROM v_city;
\echo == 3b a new column takes the old name; the view still reads the renamed one
ALTER TABLE m ADD COLUMN city integer;
SELECT pg_get_viewdef('v_city'::regclass);
ALTER TABLE m DROP COLUMN city;
DROP VIEW v_city;
\echo == 4 matview blocks drop
CREATE MATERIALIZED VIEW mv AS SELECT id, town FROM m;
ALTER TABLE m DROP COLUMN town;
DROP MATERIALIZED VIEW mv;
\echo == 5 indexes go silently (single and multi-column)
CREATE INDEX i1 ON m (town); CREATE INDEX i2 ON m (name, town); CREATE INDEX i3 ON m (lower(town));
CREATE INDEX i4 ON m (name) WHERE town IS NOT NULL;
ALTER TABLE m DROP COLUMN town;
SELECT 'indexes left: ' || coalesce(string_agg(indexrelid::regclass::text, ','), '') FROM pg_index WHERE indrelid = 'm'::regclass;
\echo == 6 check constraints: single-column, multi-column
ALTER TABLE m ADD CONSTRAINT c1 CHECK (a > 0), ADD CONSTRAINT c2 CHECK (a >= b);
ALTER TABLE m DROP COLUMN a;
SELECT 'constraints left: ' || string_agg(conname, ',') FROM pg_constraint WHERE conrelid = 'm'::regclass;
\echo == 7 foreign key of a consumer blocks dropping the primary key and changing its type
CREATE TABLE orders (id integer, m_id integer REFERENCES m (id));
ALTER TABLE m DROP CONSTRAINT m_pkey;
ALTER TABLE m ALTER id TYPE text;
ALTER TABLE m ALTER id TYPE bigint;
SELECT 'fk column after widening the key: ' || format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'm_id';
DROP TABLE orders;
\echo == 8 dropping the primary key leaves NOT NULL
ALTER TABLE m DROP CONSTRAINT m_pkey;
SELECT 'id not null after dropping pk: ' || attnotnull FROM pg_attribute WHERE attrelid = 'm'::regclass AND attname = 'id';
ALTER TABLE m ADD PRIMARY KEY (id);
\echo == 9 column grant is lost on drop and add, kept on rename and on alter type
GRANT SELECT (name, n) ON m TO consumer;
ALTER TABLE m RENAME COLUMN name TO label;
ALTER TABLE m ALTER n TYPE bigint;
SELECT 'column grants: ' || string_agg(attname, ',') FROM pg_attribute WHERE attrelid = 'm'::regclass AND attacl IS NOT NULL;
ALTER TABLE m DROP COLUMN n; ALTER TABLE m ADD COLUMN n bigint;
SELECT 'column grants after drop and add of n: ' || string_agg(attname, ',') FROM pg_attribute WHERE attrelid = 'm'::regclass AND attacl IS NOT NULL;
\echo == 10 plpgsql body is not tracked, SQL-standard body is
CREATE FUNCTION f_pl() RETURNS bigint LANGUAGE plpgsql AS $$ BEGIN RETURN (SELECT sum(b) FROM m); END $$;
CREATE FUNCTION f_sql() RETURNS bigint LANGUAGE sql BEGIN ATOMIC SELECT sum(b) FROM m; END;
ALTER TABLE m DROP COLUMN b;
DROP FUNCTION f_sql;
ALTER TABLE m DROP COLUMN b;
SELECT f_pl();
\echo == 11 row security policy and trigger on a column
ALTER TABLE m ADD COLUMN p integer, ADD COLUMN q integer;
CREATE POLICY pol ON m USING (p > 0);
ALTER TABLE m DROP COLUMN p;
CREATE FUNCTION tf() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER tr BEFORE UPDATE OF q ON m FOR EACH ROW EXECUTE FUNCTION tf();
ALTER TABLE m DROP COLUMN q;
\echo == 12 publication with a column list
ALTER TABLE m ADD COLUMN r integer;
CREATE PUBLICATION pub FOR TABLE m (id, r);
ALTER TABLE m DROP COLUMN r;
DROP PUBLICATION pub;
\echo == 13 which ALTER TYPE rewrites (relfilenode changes = rewrite)
CREATE TABLE w (i integer, nu numeric(12,2), nu2 numeric(12,2), v varchar(10), d date, ts timestamp, t text);
INSERT INTO w SELECT g, g, g, 'v', now(), now(), g::text FROM generate_series(1,1000) g;
CREATE FUNCTION rw(stmt text) RETURNS text LANGUAGE plpgsql AS $$ DECLARE o oid; BEGIN
  o := pg_relation_filenode('w'); EXECUTE stmt; RETURN stmt || ' -> ' || CASE WHEN o <> pg_relation_filenode('w') THEN 'REWRITE' ELSE 'no rewrite' END; END $$;
SELECT rw('ALTER TABLE w ALTER i TYPE bigint');
SELECT rw('ALTER TABLE w ALTER nu TYPE numeric(14,2)');
SELECT rw('ALTER TABLE w ALTER nu2 TYPE numeric(14,4)');
SELECT rw('ALTER TABLE w ALTER nu TYPE numeric');
SELECT rw('ALTER TABLE w ALTER v TYPE varchar(20)');
SELECT rw('ALTER TABLE w ALTER v TYPE text');
SELECT rw('ALTER TABLE w ALTER d TYPE timestamp');
SELECT rw('ALTER TABLE w ALTER ts TYPE timestamptz');
SELECT rw('ALTER TABLE w ALTER i TYPE numeric');
SELECT rw('ALTER TABLE w ADD COLUMN x integer');
SELECT rw('ALTER TABLE w DROP COLUMN x');
SELECT rw('ALTER TABLE w RENAME COLUMN t TO t2');
\echo == 14 dropped columns count towards the limit of 1600
CREATE TABLE lim (id integer);
DO $$ BEGIN FOR i IN 1..1700 LOOP ALTER TABLE lim ADD COLUMN c integer; ALTER TABLE lim DROP COLUMN c; END LOOP; END $$;
SELECT 'highest attnum of lim: ' || max(attnum) FROM pg_attribute WHERE attrelid = 'lim'::regclass;
\echo == 15 DDL is transactional
BEGIN; ALTER TABLE w DROP COLUMN i; ALTER TABLE w RENAME TO w9; ROLLBACK;
SELECT 'w.i after rollback: ' || count(*) FROM pg_attribute WHERE attrelid = 'w'::regclass AND attname = 'i' AND NOT attisdropped;
\echo == 16 prepared statement of a consumer after a column is added
PREPARE ps AS SELECT * FROM w;
EXECUTE ps \g /dev/null
ALTER TABLE w ADD COLUMN y integer;
EXECUTE ps \g /dev/null
\echo == 17 child table of a consumer (inheritance)
CREATE TABLE child () INHERITS (w);
ALTER TABLE w DROP COLUMN y;
SELECT 'child still has y: ' || count(*) FROM pg_attribute WHERE attrelid = 'child'::regclass AND attname = 'y' AND NOT attisdropped;
\echo == 18 view with GROUP BY on the primary key blocks dropping it
CREATE VIEW g AS SELECT id, label FROM m GROUP BY id;
ALTER TABLE m DROP CONSTRAINT m_pkey;
\echo == 19 names: 63 bytes, case
CREATE TABLE nm ("City" text, city text);
ALTER TABLE nm ADD COLUMN "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa__812" text;
SELECT 'stored as: ' || attname FROM pg_attribute WHERE attrelid = 'nm'::regclass AND attname LIKE 'aaa%';
\echo == 20 narrowing with a value that does not fit; text to integer needs USING
CREATE TABLE na (big bigint, t text); INSERT INTO na VALUES (3000000000, '7');
ALTER TABLE na ALTER big TYPE integer;
ALTER TABLE na ALTER t TYPE integer;
\echo == 21 generated column of a consumer on the mirror
ALTER TABLE m ADD COLUMN gen text GENERATED ALWAYS AS (label || '!') STORED;
ALTER TABLE m DROP COLUMN label;
\echo == 22 comment and statistics target survive alter type, lost on drop and add (by construction); comment on rename
COMMENT ON COLUMN w.v IS 'kept?'; ALTER TABLE w RENAME COLUMN v TO v2; ALTER TABLE w ALTER v2 TYPE varchar(99);
SELECT 'comment: ' || col_description('w'::regclass, attnum) FROM pg_attribute WHERE attrelid = 'w'::regclass AND attname = 'v2';
