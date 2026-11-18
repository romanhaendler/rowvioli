q() { psql -U postgres -Atc "select count(*) from pg_locks where locktype='advisory'"; }
echo "--- Case 1: client waits idle, is killed hard"
(echo "select pg_advisory_lock(7);"; sleep 300) | psql -U postgres -q >/dev/null 2>&1 &
sleep 1; echo "Locks before: $(q)"; pkill -9 psql; sleep 0.3; echo "Locks 0.3 s after kill -9: $(q)"
echo "--- Case 2: client is killed hard while Postgres computes for 15 s"
psql -U postgres -q -c "select pg_advisory_lock(8), pg_sleep(15)" >/dev/null 2>&1 &
sleep 1; pkill -9 psql; sleep 2; echo "Locks 2 s after kill -9: $(q)"; sleep 15; echo "Locks 17 s after kill -9: $(q)"
echo "--- Case 3: like case 2, but client_connection_check_interval = 2s"
psql -U postgres -q -c "alter system set client_connection_check_interval='2s'" -c "select pg_reload_conf()" >/dev/null; sleep 1
psql -U postgres -q -c "select pg_advisory_lock(9), pg_sleep(15)" >/dev/null 2>&1 &
sleep 1; pkill -9 psql; sleep 4; echo "Locks 4 s after kill -9: $(q)"
