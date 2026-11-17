# 11: A lost target ends the run and is said in one line

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Opus

From the shakedown of 2026-11-18, host H4 (operation), leads from one agent: reproduce first, drop what does
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

- [ ] After a target restart during a load, no process of the old run reads the source ten seconds later; the table loads again after its pause and the mirror equals the source.
- [ ] The line `work` writes when the target is unreachable has no SQL in it.
- [ ] The tests that kill runs and workers (`tests/test_crashes.py`, `tests/test_work.py`) pass unchanged.
- [ ] The whole suite is green.

## Comments
