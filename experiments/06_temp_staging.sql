\set ON_ERROR_STOP on
CREATE TABLE t (id bigint PRIMARY KEY, linenr int, part bigint, supp bigint, qty numeric(12,2), price numeric(12,2),
  disc numeric(4,2), tax numeric(4,2), flag text, status text, ship date, commitd date, receipt date, instr text, mode text, comment text);
INSERT INTO t SELECT g, g%7, g*3, g*5, (g%50)::numeric, (g%100000)/100.0, 0.05, 0.08, 'N','O',
  date '2020-01-01'+(g%2000)::int, date '2020-01-01'+(g%1900)::int, date '2020-01-01'+(g%2100)::int,
  'DELIVER IN PERSON','TRUCK', md5(g::text) FROM generate_series(1,:n) g;
VACUUM ANALYZE t;
CREATE TABLE t__log (_run bigint, _op text, LIKE t);
SET temp_buffers='512MB';
\timing on
\echo == TEMP-Staging fuellen
CREATE TEMP TABLE s (LIKE t);
INSERT INTO s SELECT id, linenr, part, supp, qty, price, disc, tax, flag, status, ship, commitd, receipt, instr, mode,
  CASE WHEN id%100=0 THEN 'geaendert' ELSE comment END FROM t WHERE id%1000<>1;
INSERT INTO s SELECT g, 1, 1, 1, 1, 1, 0, 0, 'N','O', current_date, current_date, current_date, 'x','y','neu' FROM generate_series(:n+1, :n+:n/1000) g;
ANALYZE s;
\echo == Unterschiede berechnen, Staging ist TEMP, 2 Worker erlaubt
SET max_parallel_workers_per_gather=2;
CREATE TEMP TABLE d AS
  SELECT 'D' AS _op, m.* FROM t m WHERE NOT EXISTS (SELECT 1 FROM s WHERE s.id=m.id)
  UNION ALL
  SELECT CASE WHEN m.id IS NULL THEN 'I' ELSE 'U' END, s.* FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
ANALYZE d;
\echo == Veroeffentlichen
BEGIN;
INSERT INTO t__log SELECT 42, d.* FROM d;
DELETE FROM t m USING d WHERE d._op IN ('D','U') AND d.id=m.id;
INSERT INTO t SELECT id, linenr, part, supp, qty, price, disc, tax, flag, status, ship, commitd, receipt, instr, mode, comment FROM d WHERE _op IN ('I','U');
COMMIT;
\timing off
SELECT _op, count(*) FROM d GROUP BY 1 ORDER BY 1;
SET max_parallel_workers_per_gather=0;
SELECT count(*) AS abweichung FROM s FULL JOIN t m ON m.id=s.id WHERE s.id IS NULL OR m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == Spaltenreihenfolge: Spiegel bekommt neue Spalte, Staging hat sie an anderer Stelle
CREATE TABLE a (id int PRIMARY KEY, x text, y int); CREATE TEMP TABLE b (id int, y int, x text);
INSERT INTO a VALUES (1,'eins',10); INSERT INTO b VALUES (1,10,'eins');
SELECT count(*) AS mit_namen_gleich FROM b LEFT JOIN a ON a.id=b.id WHERE ROW(b.id,b.x,b.y) IS DISTINCT FROM ROW(a.id,a.x,a.y);
SELECT count(*) AS mit_stern FROM b LEFT JOIN a ON a.id=b.id WHERE ROW(b.*) IS DISTINCT FROM ROW(a.*);
