\timing on
\set n :n
CREATE SCHEMA raw; CREATE SCHEMA _rowvioli;
CREATE TABLE raw.t (id bigint PRIMARY KEY, linenr int, part bigint, supp bigint, qty numeric(12,2), price numeric(12,2),
  disc numeric(4,2), tax numeric(4,2), flag text, status text, ship date, commitd date, receipt date, instr text, mode text, comment text);
INSERT INTO raw.t SELECT g, g%7, g*3, g*5, (g%50)::numeric, (g%100000)/100.0, 0.05, 0.08, 'N','O',
  date '2020-01-01'+(g%2000)::int, date '2020-01-01'+(g%1900)::int, date '2020-01-01'+(g%2100)::int,
  'DELIVER IN PERSON','TRUCK', md5(g::text) FROM generate_series(1,:n) g;
VACUUM ANALYZE raw.t;
CREATE TABLE raw.t__log (_run bigint, _op "char", LIKE raw.t);
-- Staging: source with 1 % changed, 0.1 % deleted, 0.1 % new
\echo == fill staging (stands in for COPY)
CREATE UNLOGGED TABLE _rowvioli.stage (LIKE raw.t);
INSERT INTO _rowvioli.stage SELECT id, linenr, part, supp, qty, price, disc, tax, flag, status, ship, commitd, receipt, instr, mode,
  CASE WHEN id%100=0 THEN 'changed' ELSE comment END FROM raw.t WHERE id%1000<>1;
INSERT INTO _rowvioli.stage SELECT g, 1, 1, 1, 1, 1, 0, 0, 'N','O', current_date, current_date, current_date, 'x','y','new'
  FROM generate_series(:n+1, :n+:n/1000) g;
ANALYZE _rowvioli.stage;
\echo == PUBLISH (one transaction)
BEGIN;
\echo -- deleted into the log
INSERT INTO raw.t__log SELECT 42,'D', m.* FROM raw.t m WHERE NOT EXISTS (SELECT 1 FROM _rowvioli.stage s WHERE s.id=m.id);
\echo -- new and changed into the log
INSERT INTO raw.t__log SELECT 42, CASE WHEN m.id IS NULL THEN 'I' ELSE 'U' END, s.*
  FROM _rowvioli.stage s LEFT JOIN raw.t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo -- adjust the mirror
DELETE FROM raw.t m USING raw.t__log l WHERE l._run=42 AND l._op IN ('D','U') AND l.id=m.id;
INSERT INTO raw.t SELECT id, linenr, part, supp, qty, price, disc, tax, flag, status, ship, commitd, receipt, instr, mode, comment
  FROM raw.t__log WHERE _run=42 AND _op IN ('I','U');
COMMIT;
SELECT _op, count(*) FROM raw.t__log GROUP BY 1 ORDER BY 1;
SELECT count(*) AS mirror FROM raw.t;
SELECT count(*) AS deviation FROM (SELECT * FROM raw.t EXCEPT SELECT * FROM _rowvioli.stage) x;
\echo == unchanged run (compare only)
SELECT count(*) FROM _rowvioli.stage s LEFT JOIN raw.t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == keyless: replace everything in one transaction
BEGIN; DELETE FROM raw.t; INSERT INTO raw.t SELECT * FROM _rowvioli.stage; COMMIT;
