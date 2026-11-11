P="psql -U postgres -q -At"
# Worker: 40 Runden holen / arbeiten / fertig melden / Sperre freigeben
for i in $(seq 1 40); do printf "SELECT _etl.claim(:'w') AS lauf \\\\gset\nSELECT pg_sleep(0.15 + random()*0.2);\nSELECT _etl.done(NULLIF(:'lauf','')::bigint);\nSELECT _etl.unlock(NULLIF(:'lauf','')::bigint);\n"; done > /tmp/worker.sql
# Messfuehler: zaehlt 600-mal die gehaltenen Sperren je Quelle
$P -c "DO \$\$ BEGIN FOR i IN 1..600 LOOP INSERT INTO probe SELECT count(*) FILTER (WHERE classid=1), count(*) FILTER (WHERE classid=2) FROM pg_locks WHERE locktype='advisory' AND objsubid=2 AND classid>0; PERFORM pg_sleep(0.02); END LOOP; END \$\$" &
# ein Worker, der eine Tabelle holt und dann hart beendet wird
(echo "SELECT _etl.claim('opfer');"; sleep 60) | psql -U postgres -q -At >/tmp/opfer.out 2>&1 &
sleep 0.5; OPFER=$(pgrep -f "psql -U postgres -q -At$" | head -1)
for w in $(seq 1 12); do $P -v w=w$w -f /tmp/worker.sql >/dev/null 2>/tmp/err$w & done
sleep 1; kill -9 $OPFER; echo "Opfer hatte Lauf $(cat /tmp/opfer.out) und wurde hart beendet"
wait $(jobs -p | head -13 | tail -12) 2>/dev/null; sleep 13
$P -c "SELECT 'hoechste Gleichzeitigkeit erp (Grenze 4): '||max(erp)||', crm (Grenze 2): '||max(crm) FROM probe"
$P -c "SELECT 'Messpunkte ueber der Grenze: '||count(*) FROM probe WHERE erp>4 OR crm>2"
$P -c "SELECT 'Laeufe nach Status: '||string_agg(status||'='||n, ', ' ORDER BY status) FROM (SELECT status, count(*) n FROM _etl.runs GROUP BY 1) x"
$P -c "SELECT 'Tabellen mit genau einem ok: '||count(*) FROM (SELECT tabelle_id FROM _etl.runs WHERE status='ok' GROUP BY 1 HAVING count(*)=1) x"
$P -c "SELECT 'gestorbener Lauf: '||lauf||', Worker '||worker||', neuer Versuch: '||(SELECT lauf||' ('||status||', Versuch '||versuch||', Worker '||worker||')' FROM _etl.runs n WHERE n.tabelle_id=r.tabelle_id AND n.versuch=2) FROM _etl.runs r WHERE status='gestorben'"
cat /tmp/err* | sort | uniq -c | head -5
