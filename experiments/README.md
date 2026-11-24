# Experiments

The scripts behind the numbers in `docs/measurements.md`. Each runs in a throwaway Postgres and needs only Docker.

## Running them

```sh
cd rowvioli/experiments
docker run -d --name rowvioli-exp --cpus 2 --memory 4g --shm-size 1g \
  -e POSTGRES_PASSWORD=x -v "$PWD":/exp:ro postgres:16-alpine -c work_mem=256MB
sleep 6

docker exec rowvioli-exp psql -U postgres -q -v n=1000000 -f /exp/01_publish.sql
docker exec rowvioli-exp psql -U postgres -q -f /exp/02_wide_table.sql
docker exec rowvioli-exp psql -U postgres -q -v n=10000000 -f /exp/03_diff_upfront.sql
docker exec rowvioli-exp sh /exp/04_hard_kill.sh
docker exec rowvioli-exp psql -U postgres -q -f /exp/05_claim.sql && docker exec rowvioli-exp sh /exp/05_claim.sh
docker exec rowvioli-exp psql -U postgres -q -v n=10000000 -f /exp/06_temp_staging.sql
docker exec rowvioli-exp psql -U postgres -q -f /exp/09_schema_changes.sql

docker rm -f rowvioli-exp

uv run --with pynacl python 07_secrets.py     # needs no database

docker run -d --name rowvioli-exp8 -e POSTGRES_PASSWORD=x -p 54408:5432 postgres:16-alpine
sleep 6
uv run --with adbc-driver-postgresql --with pyarrow --with "psycopg[binary]" --with pgpq python 08_drivers.py
docker rm -f rowvioli-exp8
```

Several scripts create tables and schemas with the same names. Restart the container or create a fresh database before each script.

## What each script shows

| Script | Question | Result |
|---|---|---|
| `01_publish.sql` | How long do compare and apply take in one transaction? | 1.9 s at 10⁶ rows, 59 s at 10⁷ |
| `02_wide_table.sql` | Does the row comparison hold up at 900 columns? | 5.7 s for 100,000 rows |
| `03_diff_upfront.sql` | What is gained by computing the diff before the transaction? | 26 to 40 s compare, 15 s transaction |
| `04_hard_kill.sh` | When does Postgres release the lock of a client ended with `kill -9`? | at once, or when the running statement ends |
| `05_claim.sql`, `05_claim.sh` | Does the per-source limit hold with 12 concurrent workers? Is a dead run retried? | yes, yes |
| `06_temp_staging.sql` | What does a TEMP staging table cost? Does `ROW(...)` compare by position or by name? | no multi-core compare; by position |
| `07_secrets.py` | Does sealed-box encryption have the properties the encrypted connections rely on? | yes, all six |
| `08_drivers.py` | Can ADBC alone carry the control connection, or is a second Postgres driver needed? | ADBC alone can |
| `09_schema_changes.sql` | Does the design of schema changes (`.scratch/schema-changes/strategy.md`) hold in Postgres 16: column goes and comes, widening, key change, rename proof, locks, `pg_notify`, the ledger? | each claim prints `ok` or `FAIL: ...`; all `ok`, with the caveats in the notes it prints |

## Known quirks

- `01` was measured with the default `work_mem = 4MB`, without the `-c work_mem=256MB` switch from the call above.
- `02` ends with a shared-memory error when the container runs without `--shm-size 1g`. The numbers before it are valid.
- `03` fails at its final equality check without `--shm-size 1g`. The same check passes in `06`.
- `05_claim.sh` writes many syntax errors to `/tmp/err*`. They come from idle rounds in which a worker got nothing and are harmless.
- `05` shows the claim of the first round: waiting runs and one counting lock per source. The concept now claims due tables with one counting lock for the whole target.
- `06` ends with an error on purpose: the last query shows that `ROW(b.*)` does not work when the column order differs.
- `08` connects from the host to port 54408 and takes the number of rows as an optional argument, one million by default.
- `09` runs in seconds, needs no `--shm-size`, and connects to itself with `dblink` (`host=127.0.0.1`, password `x`) to play a second session in P8 and P9. It prints `ERROR:  division by zero` in P9 on purpose: that is the transaction that fails after `pg_notify`.
