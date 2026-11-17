P="psql -U postgres -q -At"
# Worker: 40 rounds of claim / work / report done / release the lock
for i in $(seq 1 40); do printf "SELECT _rowvioli.claim(:'w') AS run \\\\gset\nSELECT pg_sleep(0.15 + random()*0.2);\nSELECT _rowvioli.done(NULLIF(:'run','')::bigint);\nSELECT _rowvioli.unlock(NULLIF(:'run','')::bigint);\n"; done > /tmp/worker.sql
# Probe: counts the held locks per source 600 times
$P -c "DO \$\$ BEGIN FOR i IN 1..600 LOOP INSERT INTO probe SELECT count(*) FILTER (WHERE classid=1), count(*) FILTER (WHERE classid=2) FROM pg_locks WHERE locktype='advisory' AND objsubid=2 AND classid>0; PERFORM pg_sleep(0.02); END LOOP; END \$\$" &
# a worker that claims a table and is then killed hard
(echo "SELECT _rowvioli.claim('victim');"; sleep 60) | psql -U postgres -q -At >/tmp/victim.out 2>&1 &
sleep 0.5; VICTIM=$(pgrep -f "psql -U postgres -q -At$" | head -1)
for w in $(seq 1 12); do $P -v w=w$w -f /tmp/worker.sql >/dev/null 2>/tmp/err$w & done
sleep 1; kill -9 $VICTIM; echo "Victim had run $(cat /tmp/victim.out) and was killed hard"
wait $(jobs -p | head -13 | tail -12) 2>/dev/null; sleep 13
$P -c "SELECT 'highest concurrency erp (limit 4): '||max(erp)||', crm (limit 2): '||max(crm) FROM probe"
$P -c "SELECT 'Sample points over the limit: '||count(*) FROM probe WHERE erp>4 OR crm>2"
$P -c "SELECT 'Runs by status: '||string_agg(status||'='||n, ', ' ORDER BY status) FROM (SELECT status, count(*) n FROM _rowvioli.runs GROUP BY 1) x"
$P -c "SELECT 'Tables with exactly one ok: '||count(*) FROM (SELECT table_id FROM _rowvioli.runs WHERE status='ok' GROUP BY 1 HAVING count(*)=1) x"
$P -c "SELECT 'dead run: '||run||', Worker '||worker||', new attempt: '||(SELECT run||' ('||status||', attempt '||attempt||', Worker '||worker||')' FROM _rowvioli.runs n WHERE n.table_id=r.table_id AND n.attempt=2) FROM _rowvioli.runs r WHERE status='dead'"
cat /tmp/err* | sort | uniq -c | head -5
