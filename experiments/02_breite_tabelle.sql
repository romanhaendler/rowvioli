\set ON_ERROR_STOP on
SELECT format('CREATE TABLE t (id bigint PRIMARY KEY, %s)', string_agg(format('c%s %s', i, CASE i%3 WHEN 0 THEN 'int' WHEN 1 THEN 'numeric(12,2)' ELSE 'text' END), ', ')) FROM generate_series(1,899) i \gexec
SELECT format('INSERT INTO t SELECT g, %s FROM generate_series(1,100000) g', string_agg(CASE i%3 WHEN 0 THEN format('g+%s', i) WHEN 1 THEN format('(g%%1000+%s)/100.0', i) ELSE format('substr(md5((g+%s)::text),1,8)', i) END, ', ')) FROM generate_series(1,899) i \gexec
VACUUM ANALYZE t;
CREATE UNLOGGED TABLE s (LIKE t);
INSERT INTO s SELECT * FROM t;
ANALYZE s;
SELECT pg_size_pretty(pg_total_relation_size('t')) AS groesse_spiegel;
\timing on
\echo == Grundlast: nur Join auf dem Schluessel, kein Vergleich
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL;
\echo == unveraendert: ROW IS DISTINCT FROM ueber 900 Spalten
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == Alternative: Hash der Zeile als Text
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR md5(s::text) <> md5(m::text);
\echo == Alternative: EXCEPT
SELECT count(*) FROM (SELECT * FROM s EXCEPT SELECT * FROM t) x;
\timing off
UPDATE s SET c899 = 'anders' WHERE id%100=0;
ANALYZE s;
\timing on
\echo == 1 % geaendert in der letzten Spalte
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == dasselbe mit work_mem 256MB
SET work_mem='256MB';
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
