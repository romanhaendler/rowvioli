# Visibility: a worker says what it does, `status` shows what is

Status: resolved

## Problem Statement

Whoever starts `rowvioli work` sees nothing. The process prints no line when it starts, none when it loads a table, none when a run fails and none while it waits. The only line it ever writes is "the target is unreachable". The owner played with it in a demo set-up and could not tell a worker that waits from a worker that hangs.

Everything worth knowing is in the target (`_rowvioli.status`, `_rowvioli.runs`), but looking at it needs `psql` and a query typed by hand. And the status view alone left a question open on the first try: a table showed `ok` with an age above its maximum age, and nothing on the screen said that it was simply due and that no worker was running.

The run processes already tell their worker both things that matter, the claim and the answer. The worker reads them and throws them away.

## Solution

One sentence carries it: **the target stays the truth, a worker only says what it does, and `rowvioli status` shows what is.**

**A worker says what it does**, one line per event on stderr:

```
2026-11-12 14:03:00 worker mac:4711 started with 4 slots on dwh
2026-11-12 14:03:01 raw_shop.orders started, run 17
2026-11-12 14:03:01 raw_shop.orders ok after 0.4s: 0 inserted, 3 updated, 10 deleted
2026-11-12 14:03:05 raw_crm.contacts failed after 2.1s: 62 % of the rows would be deleted
2026-11-12 14:03:05 nothing due, next: raw_shop.orders at 14:04:01
2026-11-12 14:09:12 stopping, 1 run finishes
```

Nothing is stored for it and nothing reads it. The lines are for a person at a terminal and for the log system the operator already has (journald, Docker). `run` says the same lines, because it is the same loop; its answer on stdout stays as it is.

**`rowvioli status` shows what is**: the status view as a table, without `psql`.

```
$ rowvioli status
source  table             max_age  age    due     status   reason
shop    public.orders     1m       3m     now     ok
shop    public.customers  1h       1h 3m  now     loading  485,000 of about 1,000,000 rows
erp     dbo.items         1h       40m    in 20m  ok
crm     contacts          1d       3h     in 4m   failed   62 % of the rows would be deleted
```

The column `due` answers the owner's question: `ok` with `due now` means the last run succeeded, the table is due, and nobody has taken it yet.

## User Stories

### A worker says what it does

1. As an operator, I want `work` to write a line when it starts, with its worker name, its slots and the database it is connected to, so that I see that it runs and where.
2. As an operator, I want a line when a run starts, with the target table and the run number, so that I see that something is being processed right now.
3. As an operator, I want a line when a run ends successfully, with its duration and the rows inserted, updated and deleted, so that I see what a load did without a query.
4. As an operator, I want a line when a run fails, with its duration and the reason, so that a failure shows up where I am looking.
5. As an operator, I want the failure line to carry the same reason as the status view and `runs`, so that there is one wording to search for.
6. As an operator, I want a run ended after `max_seconds` to give a failure line with that reason, so that I see why it stopped.
7. As an operator, I want a run that died after its claim to give a failure line with `worker lost`, so that a killed run process is not silent.
8. As an operator, I want a run process that ended before it claimed anything to give a line with its exit code, so that a broken installation does not look like "nothing due".
9. As an operator, I want one line when the worker has nothing to do, naming the table that is due next and when, so that I can tell waiting from hanging.
10. As an operator, I want that line once per change from busy to waiting and not every two seconds, so that a quiet night gives a short log.
11. As an operator, I want the waiting line to say `nothing due` and no table when no enabled table exists, so that an empty definition is recognisable.
12. As an operator, I want the line about an unreachable target to stay, once per outage, in the same format as the others, so that all lines of a worker read alike.
13. As an operator, I want a line when the worker is asked to stop, with the number of runs it lets finish, so that I know why it has not ended yet (decision 33).
14. As an operator, I want every line to begin with date and time, so that lines copied out of a terminal or a file can still be placed in time.
15. As an operator, I want every line to be one line of plain text, so that `grep`, journald and Docker handle it without a parser.
16. As an operator, I want the lines on stderr, so that they never mix with an answer on stdout.
17. As an operator of several workers, I want each worker to say only what it does itself, so that the lines of one machine tell that machine's story. What the others do is in the status view.
18. As a security officer, I want the lines to contain nothing but what is already scrubbed, and the stderr of the run processes to stay discarded, so that no driver message carries a connection value into a log (open point F4, decision 32).
19. As an operator with cron, I want `run` to say the same start, end and failure lines on stderr, so that one-shot and permanent operation leave the same trace.
20. As a pipeline author, I want the answer of `run` on stdout and its exit codes unchanged, so that nothing that parses it today breaks.
21. As an operator, I want no setting for the lines (no level, no file, no format switch), so that there is nothing to configure and nothing to get wrong.

### `status` shows what is

22. As an operator, I want `rowvioli status` to print every enabled table with source, source table, maximum age, age, due, status and reason, so that I see the state of the target without `psql`.
23. As an operator, I want durations written the way the definition writes them (`5m`, `1h 3m`), so that I can compare age and maximum age at a glance.
24. As an operator, I want a column `due` that says `now` for a table that is due and `in 20m` otherwise, so that `ok` with an age above the maximum age explains itself.
25. As an operator, I want a loading table to show its progress in place of a reason (`485,000 of about 1,000,000 rows`), so that a long run is not a black box.
26. As an operator, I want a table that was never loaded to show `new` and an empty age, so that it is not mistaken for a failure.
27. As an operator, I want a table whose run died to show `failed` with `worker lost`, as the view does, so that the command adds no status of its own.
28. As an operator, I want `rowvioli status erp` and `rowvioli status erp dbo.Orders` to narrow the output the way `run` takes names, so that there is one way to name things.
29. As an operator, I want the tables ordered by source and source table, so that the output is stable between two calls and `watch rowvioli status` does not jump.
30. As an operator, I want `status` to need `ROWVIOLI_TARGET_URL` and nothing else, no key and no connector, so that it runs wherever `apply` runs.
31. As an operator, I want `status` to need no right beyond reading the status view, so that the role of a web UI is enough for it.
32. As an operator, I want `status` to say "run `rowvioli init` first" on a target without `_rowvioli`, as `apply` does, so that the first mistake has a clear answer.
33. As an operator, I want `status` to exit with 0 whenever it could print the state, whatever the state is, so that it is a view and not a check.
34. As an operator, I want an empty progress when the reading role cannot see `pg_stat_progress_copy`, without an error, so that a restricted role still gets the rest.

### Documents

35. As a reader of the README, I want the usage block to end with `rowvioli status`, so that the first thing I learn after starting a worker is how to look.
36. As a reader of the README, I want the lines of a worker listed with one example each under "Workers" or "Operation", so that I know what to expect in my log system.
37. As a reader of the decisions, I want one new decision that says why a worker's lines are not stored and why there is no log setting, so that nobody adds a log table later without knowing the reason.

## Implementation Decisions

- **Nothing is stored and the schema does not change.** No table, no column, no new schema version. `runs` is already the log that can be queried; the lines are its echo for people.
- **The worker loop writes the lines, the run processes do not.** A run process keeps saying its claim and its answer to the worker on its stdout, and its stderr stays discarded. The loop turns exactly those two messages into the start line and the end line. The duration is the time between the two, measured by the loop.
- **Failures the loop decides itself use the same line.** Ended after `max_seconds` and `worker lost` are answers the loop already forms; they are written as failure lines with those reasons.
- **The waiting line needs the next due table.** The loop asks for the enabled table with the earliest `due_at` that is not loading, on its existing connection, when it changes from busy to waiting. A due time in the past is written as `due since HH:MM:SS` (it is due but not claimable, for example because `parallel` or `max_running` is full or another worker has it). It is written again only after a run of this worker ended or the target was unreachable in between.
- **One format.** Local date and time to the second, a space, the text. No levels, no JSON, no colours, no difference between a terminal and a pipe. Numbers in the lines are plain; the duration has one decimal.
- **Everything on stderr**, for `run` and `work` alike. The existing line about the unreachable target gets the timestamp and stays once per outage. `run` writes no start line of the worker and no waiting line: it has nothing to wait for. Its stdout answer and exit codes are untouched.
- **The start line names the database as the target reports it** (`current_database()`), never a part of `ROWVIOLI_TARGET_URL`, so that no fragment of a connection value can reach a log.
- **`status` is a new command** next to `init`, `key`, `list`, `apply`, `run`, `work`. It takes an optional source and an optional table like `run`, reads `_rowvioli.status` and prints an aligned text table. It formats; it computes nothing: status, due time and progress come from the view. The only thing it derives is the wording of `due` from `due_at` and the target's clock.
- **`status` shows enabled tables only.** A disabled table is no longer part of the definition.
- **Durations are written in the definition's notation**, largest two units, the same notation `apply` reads. If the program already has a function for this direction, it is used; otherwise one small one is added next to the one that parses.
- **A new decision is appended to `docs/decisions.md`** under the next number, with the rejected alternatives: a log table in the target (`runs` is that), Python's `logging` with levels and handlers (nothing to configure is the point), JSON lines (the structured data is in the target), progress lines during a run (the status view has it, a worker writes nothing for it).
- **Documents.** README: the usage block, "Commands", "Workers" or "Operation" for the lines, and the web UI row "Show complete log lines" names what the worker's log system now receives. GLOSSARY: no new term; the lines are "what a worker says", and "log" keeps meaning the change log and `runs`.

### Who implements

The owner's rule for this and every later spec: **before implementing a ticket, decide which model it needs, and take the smallest that fits.** Sonnet and Opus are the standard, chosen by the weight of the ticket. Fable should practically never be needed; if a ticket seems to need it, that is a sign the ticket is too large or unclear, and it is cut or clarified first. Opus does the review at the end.

Estimate for this spec, to be checked again per ticket:

| Work | Model |
|---|---|
| The lines of the worker loop | Sonnet. The messages exist; the care goes into the waiting line and into keeping secrets out. |
| The command `status` | Sonnet. Formatting over an existing view. |
| Documents and the new decision | Sonnet. |
| Review of the whole at the end | Opus. |

## Testing Decisions

- **The existing seam, nothing new.** Tests start the commands as real processes against real PostgreSQL in Docker and look only at what a user sees (`.scratch/v0.1/spec.md`, "Testing Decisions"). No test imports a module of the program. What a user sees now includes the stderr of `work` and `run` and the stdout of `status`.
- **A good test** states one sentence of this spec and would pass if the loop or the command were rewritten. It matches the parts of a line that carry meaning (table, `ok`, the counts, the reason), not the timestamp and not the whole line byte for byte.
- **No simulated clock.** As in `tests/test_status.py`, facts with fixed dates are written into `_rowvioli.tables` and the output is read.

What is tested:

1. `work` writes a start line with its slots and the database, a start line and an `ok` line with the counts for a table it loads, and the counts equal those in `runs` (prior art: `tests/test_work.py`, which starts `work` as a process).
2. A failing table gives a failure line with the reason the status view shows.
3. A run ended after `max_seconds` gives a failure line with that reason (prior art: the existing `max_seconds` test).
4. A run process killed after its claim gives a failure line with `worker lost` (prior art: `tests/test_crashes.py`).
5. With nothing due, `work` writes the waiting line once, names the table due next, and does not repeat it over several rounds of the loop.
6. On SIGTERM during a run, `work` writes the stopping line and the run's `ok` line, and exits 0 (prior art: the existing SIGTERM test).
7. A secret of the connection that a failing source quotes back does not appear on the stderr of `work` or `run` (prior art: `tests/test_secrets.py`).
8. `run` writes the start and end lines on stderr, and its stdout is still exactly one JSON answer (the existing `run` tests stay green unchanged).
9. `status` prints one row per enabled table with the view's status; a table with an age above its maximum age shows `due now`, a fresh one `in …`; a never-loaded one shows `new`.
10. `status` shows the reason of a failed table and `worker lost` for a dead run.
11. `status <source>` and `status <source> <table>` narrow the rows; a disabled table is not shown.
12. `status` works with `ROWVIOLI_TARGET_URL` alone, exits 0 with failed tables present, and names `rowvioli init` on a target without the schema.

Not tested: the progress text during a load. It needs a run slow enough to catch in `pg_stat_progress_copy`; the view's columns are already covered, and the command only prints them.

Disk space: the harness's rule stands. Containers and volumes are removed after the session.

## Out of Scope

- A command for past runs (`rowvioli runs`). `_rowvioli.runs` is one query away, and the worker's lines cover "what happened last night". Open for the owner, see below.
- `status --watch`, JSON output of `status`, colours. `watch rowvioli status` and SQL on the view exist.
- Log levels, a quiet or verbose switch, log files, rotation, a format setting.
- Progress lines while a run is loading.
- A log table in the target, or any change to the schema `_rowvioli`.
- Tracebacks or driver output of run processes. They stay discarded (open point F4).
- A status `due` or `overdue` in the view. The view keeps `new`, `loading`, `ok`, `failed`; `due` is a column of the command, derived from `due_at`.
- The web UI.
- Metrics (Prometheus, StatsD).

## Further Notes

- The owner asked for this on 2026-11-12 after playing with a demo set-up next to the checkout (`../rowvioli-demo`, not part of this repo): "what I am definitely missing is logging", and asked how to look at information and how `work` could communicate that something is being processed.
- Decided here by assumption, because the owner did not answer the two open questions of the brainstorm: plain text instead of JSON lines, and the waiting line is included although it is the only part that needs an additional query.
- Also by assumption: the lines go to stderr (the brainstorm said stdout). The reason is `run`, whose stdout is an answer that others parse; with stderr, `run` and `work` follow one rule.
- Also by assumption: `status` is built now. The brainstorm recommended waiting until `psql` gets tiresome; the owner asked for ways to look at information to be built in.
- Open for the owner: whether past runs get a command too. If yes, the smallest form is `rowvioli status <source> <table>` printing that table's last runs below its row, not a new command.
- The owner's rule for this repo applies: one carrying idea, no pile of rules. The measure for the implementation is that the README needs one paragraph for the lines and one for `status`, and that neither introduces a setting.
- The demo set-up defines a shell alias `status` on the view; once the command exists, the alias is dropped there and `rowvioli status` takes its place.
