# 11: A lost target ends the run and is said in one line

**Blocked by:** none

**Status:** resolved

**Model:** Opus

From the shakedown of 2026-11-17, host H4 (operation), leads from one agent: reproduce first, drop what does
not go red. Repros: restart the target (`docker restart`) twelve seconds into a load of a table that takes
over a minute to read (a source view with `pg_sleep`), and a target on a 200 MB tmpfs
(`--tmpfs /var/lib/postgresql/data:size=200m`) with a table too large for it.

## What to build

- **A run whose connection to the target is lost keeps reading the source to its end** (89 s more, measured),
  and a retry of the same table starts meanwhile, so two reads of an expensive source overlap. The mirror is
  never touched. The run's process ends when its control connection is gone: find out why it does not
  today (the connection is the run's lock and sign of life, decision 8 and "Failures" in the README) and
  what the smallest way is to notice within seconds, without a heartbeat table and without a second concept.
- **The worker's log and `run` print the whole claim query** (25 lines, `Query was: SELECT ...`) when the
  target drops a connection. A reason is one line (shakedown spec, "A reason is one line"): the same rule for
  what `work` and `run` write about the target.
- **A full disk on the target reads as `connection to the target lost` / `worker lost`** the first time,
  because Postgres restarts. If the cause can be had cheaply (the server's message before the drop), say it;
  if not, record it as a known limit with the sentence for the documents.

## Acceptance criteria

- [x] After a target restart during a load, no process of the old run reads the source ten seconds later; the table loads again after its pause and the mirror equals the source.
- [x] The line `work` writes when the target is unreachable has no SQL in it.
- [x] The tests that kill runs and workers (`tests/test_crashes.py`, `tests/test_work.py`) pass unchanged.
- [x] The whole suite is green.

## Comments

Built (branch `p2-11`, from `part-2` 111f4fa); each fix has a test that went red on the old code.

- **What the run's process did.** Reproduced with `docker restart` of the target 12 s into a load of a view that sleeps 1 s per row (90 rows): the run's process lived 77.9 s more, until the source was read, and from 49 s on a retry read the source beside it (two reads for 29 s). `sample` of the process: the main thread sat in the postgres connector's `cur.execute`, i.e. `PQexecParams` of the source's `COPY ... TO STDOUT`, in `poll` on the source socket. The target connection lay idle meanwhile: its death (the server's FATAL and close) was in its socket, and nobody looks there before the next statement, which comes only after the read. Not a COPY that buffers, not the connector's read of the target.
- **What I built.** The worker already asks the target every two seconds; it now also asks whether the tables of its runs are still `loading` (the status view, i.e. the table lock, decision 7), and kills a run whose table is not and that has not answered. It says `connection to the target lost`. No heartbeat, no second connection: the lock is the sign of life, read by the connection the worker has. A run that already answered is not touched, so a run that just published and closed is never counted as lost. `max_seconds` and SIGTERM are unchanged (a stopping worker still ends a lost run, which could not publish anyway). After: the old run's process was gone 3.2 s after the restart (test bound: 10 s). Without the worker reaching the target nothing changes: a run then ends as before, at its next statement or after `max_seconds`.
- **One line.** `work`'s line for an unreachable target and `run`'s message use `reason_line`, so the 25 lines of the claim query are gone (`FATAL:  terminating connection due to administrator command`).
- **Full disk: a known limit, not built.** On a 200 MB tmpfs the run fails with Postgres's message (`could not extend file ...: No space left on device`) while staging, diffing or inserting. Only when the write-ahead log cannot grow does Postgres PANIC and restart; then the run reads `connection to the target lost` and the status `worker lost`. The run has the cause in hand (`PANIC:  could not write to file "pg_wal/xlogtemp.76": No space left on device`, measured), and appending it to `connection to the target lost` in `load.main` would be one line, but it changes the reason `tests/test_crashes.py` expects exactly, which this ticket keeps unchanged: the owner's call. Sentence in `docs/open-points.md`: "A full disk on the target can read as `connection to the target lost`, and the status as `worker lost`. ..."
- **Dropped / left.** The source side: a Postgres source keeps computing the read of an ended run until it next sends rows (measured: the restart test's `CREATE OR REPLACE VIEW` waited 57 s for it). That holds for `max_seconds` and hard kills too; recorded as a known limit. Setting `client_connection_check_interval` on the source session in the postgres connector would end it, but fails on Postgres before 14 and is the connector's business, not this ticket's.
- **Documents.** CHANGELOG (two lines under Fixed), open points (two known limits), README (the unreachable line is one line).

