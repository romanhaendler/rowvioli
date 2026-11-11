# `work`, order, limits, `max_seconds`

Status: ready-for-agent
Blocked by: 03

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

The `work` command (`--slots`, target address, `ROWVIOLI_KEY_FILE`), most-overdue-first, both limits through the one counting lock, ending a run after `max_seconds`. User stories 15, 16, 21-24.

## Acceptance criteria

- [ ] Spec tests 13, 14, 19 pass.

## Comments

Observations for spec questions 2 and 3 (impl-06):

- **One counting lock holds both limits (q2): yes.** Spec test 14 runs 6 workers with 4 slots each against two sources (erp `parallel = 2`, crm `parallel = 3`, 10 slow tables each) with `max_running = 4`, and probes `pg_locks` every 20 ms. Over many repetitions the probe never saw more than `parallel` per source or 4 in total, and both erp's 2 and the total of 4 were reached. With the counting lock replaced by `SELECT 1`, the same test failed 2 of 3 times with 5 table locks held in total. So the lock is what holds the limit, not luck. A smaller first version (3 workers with 3 slots, 2 x 5 tables) never broke the limit even without the lock: claims have to overlap within a few milliseconds, and Python's process start spreads them. A probe at low load proves nothing.
- **Cost of a fresh process per run (q3).** For a table of 100 rows: the run inside the target (claim to publish, `runs.finished_at - started_at`) took 0.055-0.10 s. Starting Python and importing the program (pyarrow, ADBC) took 0.115 s, against 0.014 s for a bare Python. `rowvioli run erp` took 0.43-0.56 s wall time in total, including its own start and two questions to the target. So for a small table the fresh process costs about twice the run itself. That is fine for tables loaded every few minutes. It is not fine for hundreds of tiny tables per minute on one machine.

Deviations and gaps:

- The run process prints a first JSON line `{"claimed", "run", "max_seconds"}` right after the claim. This is how the worker learns which table a process holds and when its `max_seconds` starts. `max_seconds` counts from when the worker reads that line, not from `runs.started_at`.
- Reason for a run that was ended: `ended by worker <host:pid> after max_seconds = N`. The worker kills first (SIGKILL), then writes the reason on the table and the run through its own connection, only if the run is still `running`. Between the two the view shows `worker lost` for a few milliseconds. Writing first would be wrong: a run that published in between would get a reason it does not deserve.
- `max_seconds` is the source's only. A table-level `max_seconds` (README) is still ignored by `apply`.
- When a run process dies before it claims anything (for example the claim itself fails), `run` starts no more processes, waits for its other runs and exits 1. Without this it started new processes forever. `work` tries again after two seconds.
- A worker asks again at once only when a run that had claimed something ends. When the limits are full, each worker still starts up to `--slots` processes every two seconds that claim nothing (about 0.12 s CPU each), because the question "is something due" does not know the limits. Harmless in the prototype, wasteful with many workers.
- Killing `work` itself leaves its run processes as orphans. Nobody ends them after `max_seconds`. The README does not say what happens to the runs when the service is stopped.
- `work --slots` defaults to 4, as in the README examples.
