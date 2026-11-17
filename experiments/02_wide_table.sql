\set ON_ERROR_STOP on
SELECT format('CREATE TABLE t (id bigint PRIMARY KEY, %s)', string_agg(format('c%s %s', i, CASE i%3 WHEN 0 THEN 'int' WHEN 1 THEN 'numeric(12,2)' ELSE 'text' END), ', ')) FROM generate_series(1,899) i \gexec
SELECT format('INSERT INTO t SELECT g, %s FROM generate_series(1,100000) g', string_agg(CASE i%3 WHEN 0 THEN format('g+%s', i) WHEN 1 THEN format('(g%%1000+%s)/100.0', i) ELSE format('substr(md5((g+%s)::text),1,8)', i) END, ', ')) FROM generate_series(1,899) i \gexec
VACUUM ANALYZE t;
CREATE UNLOGGED TABLE s (LIKE t);
INSERT INTO s SELECT * FROM t;
ANALYZE s;
SELECT pg_size_pretty(pg_total_relation_size('t')) AS size_mirror;
\timing on
\echo == baseline: only the join on the key, no comparison
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL;
\echo == unchanged: ROW IS DISTINCT FROM over 900 columns
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == alternative: hash of the row as text
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR md5(s::text) <> md5(m::text);
\echo == alternative: EXCEPT
SELECT count(*) FROM (SELECT * FROM s EXCEPT SELECT * FROM t) x;
\timing off
UPDATE s SET c899 = 'different' WHERE id%100=0;
ANALYZE s;
\timing on
\echo == 1 % changed in the last column
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
\echo == the same with work_mem 256MB
SET work_mem='256MB';
SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT count(*) FROM s LEFT JOIN t m ON m.id=s.id WHERE m.id IS NULL OR ROW(s.*) IS DISTINCT FROM ROW(m.*);
