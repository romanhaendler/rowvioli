# Shakedown 2026-11-17: the entries that had not run, and P1 and P4 again

Status: needs-triage (taken up in `.scratch/out-of-the-box/`, tickets 09 to 14; what stays is listed below)

Two waves on the wheel built from the branch `out-of-the-box`, all on Sonnet. First P1 and P4 again, beside
the review on Opus. Then the entries that had never run: H4, P3, P16, P20, P22, P23. Not run: P24. Not run
again: H1, H2, P18, P27. ✓ = reproduced by the coordinating session or confirmed in the source; the rest are
leads from one agent, and a ticket that starts from one reproduces it first.

## What they found

| From | Finding | Where it went |
|---|---|---|
| P1 | The hint `rowvioli key new creates it` sends a second machine to make a key that decrypts nothing ✓ | ticket 10, fixed |
| P1 | `kye`, `ky`, `kee` pass as connector options | ticket 10, fixed |
| P1 | `sources is not a directory`, `run customers`, a raw `@` in the target's password: messages that name no way out | ticket 10, fixed |
| P1 | After a changed `max_age` without `apply`, `status` shows the old value and says nothing | left: `status` knows the target only |
| P4 | Archiving daily files of a pattern trips the limit on deletions | README sentence (ticket 10); a table that only appends is the owner's "later" |
| P4, P20 | The history begins with the first load; two changes between two runs are one version; `_loaded_at` is the last change, not the last load; no query for "what changed in a period" | ticket 12, documents |
| P16 | An existing target table with `numeric(10,2)` fails its first run as "changed its type"; the ALTER is blocked by a view | ticket 14 |
| P16, P3 | `numeric(12,2)` arrives as `numeric`: `137.00` reads `137` | ticket 14 |
| P16 | `__log` and `__history` appear in a schema other things read; a nightly table needs a long `max_age`; a `WHERE` needs a view in the source | ticket 12, documents |
| P16 | `no such file in ***`: the scrubber hides the directory | ticket 13 |
| P20 | A consumer cannot tell a quiet source from a dead worker: the README's rights do not reach the status | ticket 13 |
| P22 | The `postgres` connector ignores every option: `incremental = "updated"`, `query = "..."` load the whole table ✓ | ticket 13 |
| P22 | An emptied source can never publish, also with `max_delete_share = 1.0` | ticket 13 |
| P3, H4 | A killed run stays `running` in `_rowvioli.runs` | ticket 13 |
| P3 | 100,000 rows of 300 columns: 271 s the first time, 83 to 139 s unchanged, most of it filling the staging table. Measured on a loaded machine with Docker's disk nearly full: the direction holds, the numbers do not | open: measure a whole run on a wide table on a quiet machine and put it beside section 2 of `docs/measurements.md` |
| H4 | A run whose target connection is lost reads the source to its end (89 s more) while a retry starts | ticket 11 |
| H4 | The whole claim query in the worker's log when the target drops a connection; a full disk on the target reads as `connection lost` the first time | ticket 11 |
| P23 | A new column in the status view touches seven files and ten places, and every target must be initialised anew | `.scratch/migration/spec.md`: views are replaced by every `init` |
| P23 | `rowvioli status` skips the version check, so a newer program would send its query to an older view (read, not run) | `.scratch/migration/spec.md` |
| P23 | The list of reserved column names stands twice in `load.py`; `print_status` works with fixed positions the tests mirror | left for the first change that touches them |
| P23 | `load()` in `tests/test_file.py` passed when nothing loaded | ticket 12, fixed |

## Wishes

Unchanged and recorded before: reading only rows from a timestamp on (P16, P22; the owner made it the first
step of the migration spec), a filter and other column names per table (P16; "not a transformation tool",
a view in the source holds), CDC, alerts on failure, REST paging by cursor, other targets (P22; unlisted or
"no"). New: moving a processed file away (P16; unlisted).

## What held up

Every guarantee of the README, each tried (P3): no half state under a reader that polled during reloads,
one run per table, a killed run retried with pauses of 59 s to 16 min, 155 to 170 MB for a million rows.
Operation (H4): SIGTERM lets the run finish, SIGKILL frees the lock within a second, a restarted target and a
cut source end in a mirror equal to the source, a clock set a day forward and back changes nothing, 270
concurrent `apply` leave one whole definition. The history query was exact at 38 of 38 moments (P20). Six of
six requests of a coding agent from the README, the guide and `--help` (P4). Eight cron scripts moved to
26 lines of TOML with equal data (P16).

P22's answer to the open point: Sling and ingestr cover the loading (more sources, incremental, CDC; their
documentation read on 2026-11-17), not the freshness model; the second half is from memory.

## Lessons for the procedure

- ✓ **Docker's own disk filled up, not the Mac's.** It has 23.5 GB; with three test suites, the shakedown's
  containers and a wide table at once, one run died with `No space left on device` and two suites showed
  hundreds of setup errors. `df -h /` saw nothing. Check `docker run --rm postgres:16-alpine df -h /`, and let
  no more than two suites run beside a wave.
- ✓ **A test session that dies hard leaves its containers.** Two pairs stood for twenty minutes with 8 GB of
  volumes and no process; they were removed by name.
- An agent's `pkill -f` by a pattern can hit another agent's process (P3). The brief should ask for a kill
  by the agent's own directory or pid.
- A persona left its worker running because its own kill was refused (P20); the coordinator ended it.
- Cost: eight agents on Sonnet, about 660k subagent tokens, 27 minutes wall clock for the slowest (H4).
