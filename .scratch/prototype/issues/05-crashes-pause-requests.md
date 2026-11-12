# Killed runs, pause, requests, readers

Status: resolved
Blocked by: 03

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

Whatever is missing so that the guarantees hold under real crashes; mostly tests. User stories 25, 26, 30, 32-35. Hold a run at each step from the SQL side as "Testing Decisions" describes; if that turns out impossible, note it in a comment on this ticket (question 6 of the spec).

## Acceptance criteria

- [ ] Spec tests 9, 10, 11, 12 pass.
- [ ] Spec test 22: `loading` is visible only while the table lock is held.

## Comments

Observations for spec question 6 (impl-05, Postgres 16, adbc-driver-postgresql 1.13.0): **yes, every step can be held from the SQL side, no hook is needed**, with two caveats.

- **Filling.** A source view with a sleep per row holds the run, but with a small table it holds it while *reading*: the target has no `_stage` yet, because the driver hands over a batch only when it is full (about 16 MB) or the source is done. To hold it inside `COPY ... _stage` with rows already in the staging table, the view has to deliver about 25 MB before the sleeping rows. The test observes this from the target: a temp table with `pg_relation_size` above zero (since impl-review without the program's statement text; diff and publishing are observed as the run's ungranted `AccessShareLock` / `RowExclusiveLock` on the mirror in `pg_locks`).
- **The sleep has to be per row.** `CROSS JOIN LATERAL (SELECT pg_sleep(...))` without a reference to the row sleeps once. A volatile SQL function called with a column (`slowly(customer_no)`) sleeps per row.
- **Diff.** `LOCK TABLE mirror IN ACCESS EXCLUSIVE MODE` holds the run at `CREATE TEMP TABLE _diff`. Only from the second run on: the first run of a table does not read the mirror.
- **Publishing.** `LOCK TABLE mirror IN EXCLUSIVE MODE` lets the diff read and holds the run at `DELETE FROM mirror`, after the change log rows were inserted inside the publishing transaction. After `kill -9` neither the mirror nor the change log changed.
- **Lock release after `kill -9`.** Immediate (about 10 ms) while the target backend waits for the client (filling). About 2 s while it waits for a lock (diff, publishing): `client_connection_check_interval = 2s` also works during a lock wait, so the table lock is released while the test still holds the mirror lock. The README's "Failures" holds.

Observation for spec question 4 (a killed server process, through ADBC):

- `pg_terminate_backend` on the run's target backend while it waits at the diff: the driver raises `OperationalError: IO: ... no connection to the server` for the running statement, and again for the `ROLLBACK` in the failure path. Before this ticket the run process ended with a traceback and no answer, so `run` printed `"tables": {}` and exited 0 although the table failed. Now the run answers `{"status": "failed", "reason": "connection to the target lost"}` and `run` exits 1. Nothing can be stored without the connection, so the status shows `failed` with `worker lost`, the lock is gone with the connection, and the mirror is unchanged. The reason is a fixed text on purpose: it cannot contain a connection value.

Deviations and gaps:

- **A run process killed with -9 is missing from the answer of `run`.** `run` prints `"tables": {}` and exits 0 although the table is `failed`. The worker loop does not know which table a run process claimed, because the process prints only at its end. The status view is right. If the run process printed its claim first (ticket 06 needs that for `max_seconds` anyway), the loop could report `worker lost` for the table and exit 1.
- **A killed run's row in `runs` stays `running`** with no `finished_at`, as the README says ("recorded as running while nobody holds its table lock" = dead). The tests assert this.
- **A request during a run that then fails makes the table due at once,** skipping the pause: `requested_at` is later than `attempted_at`. Spec test 12 covers only a request *before* a failing run (that one stays in its pause). The README's table of requests does not say which should win; not tested.
- Spec test 22 is covered twice: by the view-level test in `tests/test_status.py` (a lock taken by SQL) and in every kill test (`loading` with one held table lock before the kill, not `loading` with none after).
