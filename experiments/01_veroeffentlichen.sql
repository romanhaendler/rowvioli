\timing on
\set n :n
CREATE SCHEMA raw; CREATE SCHEMA _etl;
CREATE TABLE raw.t (id bigint PRIMARY KEY, linenr int, part bigint, supp bigint, qty numeric(12,2), price numeric(12,2),
  disc numeric(4,2), tax numeric(4,2), flag text, status text, ship date, commitd date, receipt date, instr text, mode text, comment text);
INSERT INTO raw.t SELECT g, g%7, g*3, g*5, (g%50)::numeric, (g%100000)/100.0, 0.05, 0.08, 'N','O',
  date '2020-01-01'+(g%2000)::int, date '2020-01-01'+(g%1900)::int, date '2020-01-01'+(g%2100)::int,
  'DELIVER IN PERSON','TRUCK', md5(g::text) FROM generate_series(1,:n) g;
VACUUM ANALYZE raw.t;
CREATE TABLE raw.t__log (_run bigint, _op "char", LIKE raw.t);
-- Staging: Quelle mit 1 % geaendert, 0,1 % geloescht, 0,1 % neu
\echo == staging fuellen (steht fuer COPY)
CREATE UNLOGGED TABLE _etl.stage (LIKE raw.t);
INSERT INTO _etl.stage SELECT id, linenr, part, supp, qty, price, disc, tax, flag, status, ship, commitd, receipt, instr, mode,
  CASE WHEN id%100=0 THEN 'geaendert' ELSE comment END FROM raw.t WHERE id%1000<>1;
INSERT INTO _etl.stage SELECT g, 1, 1, 1, 1, 1, 0, 0, 'N','O', current_date, current_date, current_date, 'x','y','neu'
  FROM generate_series(:n+1, :n+:n/1000) g;
ANALYZE _etl.stage;
\echo == VEROEFFENTLICHEN (eine Transaktion)
BEGIN;
\echo -- geloescht ins Protokoll
INSERT INTO raw.t__log SELECT 42,'D', m.* FROM raw.t m WHERE NOT EXISTS (SELECT 1 FROM _etl.stage s WHERE s.id=m.id);
\echo -- neu und geaendert ins Protokoll
INSERT INTO raw.t__log SELECT 42, CASE WHEN m.id IS NULL THEN 'I' ELSE 'U' END, s.*
  FROM _etl.stage s LEFT JOIN raw.t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo -- Spiegel anpassen
DELETE FROM raw.t m USING raw.t__log l WHERE l._run=42 AND l._op IN ('D','U') AND l.id=m.id;
INSERT INTO raw.t SELECT id, linenr, part, supp, qty, price, disc, tax, flag, status, ship, commitd, receipt, instr, mode, comment
  FROM raw.t__log WHERE _run=42 AND _op IN ('I','U');
COMMIT;
SELECT _op, count(*) FROM raw.t__log GROUP BY 1 ORDER BY 1;
SELECT count(*) AS spiegel FROM raw.t;
SELECT count(*) AS abweichung FROM (SELECT * FROM raw.t EXCEPT SELECT * FROM _etl.stage) x;
\echo == unveraenderter Lauf (nur Vergleich)
SELECT count(*) FROM _etl.stage s LEFT JOIN raw.t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == schluessellos: alles ersetzen in einer Transaktion
BEGIN; DELETE FROM raw.t; INSERT INTO raw.t SELECT * FROM _etl.stage; COMMIT;
