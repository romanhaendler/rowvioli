q() { psql -U postgres -Atc "select count(*) from pg_locks where locktype='advisory'"; }
echo "--- Fall 1: Client wartet untaetig, wird hart beendet"
(echo "select pg_advisory_lock(7);"; sleep 300) | psql -U postgres -q >/dev/null 2>&1 &
sleep 1; echo "Sperren vorher: $(q)"; pkill -9 psql; sleep 0.3; echo "Sperren 0,3 s nach kill -9: $(q)"
echo "--- Fall 2: Client wird hart beendet, waehrend Postgres 15 s rechnet"
psql -U postgres -q -c "select pg_advisory_lock(8), pg_sleep(15)" >/dev/null 2>&1 &
sleep 1; pkill -9 psql; sleep 2; echo "Sperren 2 s nach kill -9: $(q)"; sleep 15; echo "Sperren 17 s nach kill -9: $(q)"
echo "--- Fall 3: wie Fall 2, aber client_connection_check_interval = 2s"
psql -U postgres -q -c "alter system set client_connection_check_interval='2s'" -c "select pg_reload_conf()" >/dev/null; sleep 1
psql -U postgres -q -c "select pg_advisory_lock(9), pg_sleep(15)" >/dev/null 2>&1 &
sleep 1; pkill -9 psql; sleep 4; echo "Sperren 4 s nach kill -9: $(q)"
