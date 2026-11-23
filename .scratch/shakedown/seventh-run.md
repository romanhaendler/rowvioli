# Shakedown 2026-11-23: before 0.4.1

Status: needs-triage (what was fixed before the release is marked; what stays is listed below)

One wave of two Sonnet agents on the wheel 0.4.1 built from the branch `after-0.4.0`, narrowed to what the
release changes: a run publishes only under a target name it still owns (decision 53), Ctrl+C, a stderr that
fails and recovers, control characters in names and messages, the new messages. H4 operation through
pseudo-terminals and with `apply` during loads, also against 0.4.0 and with a mixed fleet; P18 security with a
beginner's eye for the messages. Not run: every other entry. Not covered by either: Windows, a real systemd,
an outage of the target longer than a few seconds with a refused connection, `rest` and `odbc`.
✓ = reproduced by a test that was red before its fix, or confirmed in the source by the coordinating session;
the rest are leads from one agent, and a ticket that starts from one reproduces it first.

## What they found

| From | Finding | Where it went |
|---|---|---|
| P18 | A message a command stops with is written raw: a source file or a subfolder named with an escape sequence, a connection key, a key file path ✓ | fixed in 0.4.1: every such message is written with control characters as `?` |
| P18 | A target password with an unencoded `/` is printed up to the `/` by the driver's message (`invalid integer value "…" for connection option "port"`); in 0.4.0 too ✓ | fixed in 0.4.1: the address check names the cause and prints nothing of the address |
| P18 | A target of 0.4.0 holding a name with a control character: `apply` refuses, `run` goes on, the way out works, but the old tables stay under a name nobody can type, and no page said how to drop them | documented in 0.4.1 (`docs/loading.md`, CHANGELOG) |
| P18 | The name check covers five settings: connector option keys and values, `type`, and column names that come from the source (a CSV header) are stored raw and shown raw by `psql -At` | left |
| P18 | Bidi and invisible characters (U+202E, U+200B, U+FEFF) pass in names; `status` can show a name reversed | left |
| P18 | The message for a non-ASCII digit in `max_age` or `at` says "not a whole number" where a person sees digits | left |
| H4 | Ctrl+C, and SIGTERM, do not end `work` while a query to a target that hangs is pending (a paused host, a firewall that drops packets): no line, five Ctrl+C ignored, exit only when the target answers. In 0.4.0 too: no query of the worker has a timeout | left: the one that matters most here |
| H4 | After Ctrl+C the ended tables show `worker lost` and wait out the pause of about a minute before the next start loads them | left: documented in `docs/operation.md` |
| H4 | SIGTERM to `run` ends it with no line, its runs die with it and their rows stay `running`; the pages describe SIGTERM for `work` only | left |
| H4 | `log = false` applied to a table that has a change log, or a name swap between a table with and one without a log or a key, fails every run until a person drops the log; the reason names the log, not the stale rows | left: decisions 39 and 46, the message names the way out |

## What held up

- Decision 53 in every scenario tried: a swap of two target names with locks on both sources, one table replacing another under its name, a rename with no new owner, a schema-only rename, a table removed, removed and added back, the same definition applied again, a swap and a swap back, only `max_age` changed, two parallel runs. Every mirror held its own source's rows, every log replayed to its mirror, status was true, one run repaired everything, and no run was refused that should have passed.
- The same swap on 0.4.0 showed the other table's rows in a mirror with status `ok` for a fraction of a second, sampled by polling; a 0.4.0 worker beside a 0.4.1 worker still did.
- Ctrl+C through a real pseudo-terminal, for `work` and `run`: the one line, exit code 130, no traceback, no process left; twice quickly, with SIGTERM before or after, during a restart of the target; Ctrl+Z and `fg`; closing the terminal.
- A full 16 KB volume for `2>>worker.log`, a reader that paused for 30 s, a reader that left: loading went on, the lines came back, the exit codes of `run` stayed the documented ones.
- `✔ the target is reachable again after 2s` once per outage.
- Every command that stops with a message exits with 1, never 120, with stderr closed, a broken pipe or `/dev/null`.
- No password in any of the new texts; `rowvioli status` writes no cell raw.

## Cost

Two Sonnet agents, about 25 minutes for the longer one. Images pulled: none. Every container with the label
`rowvioli-shakedown` was removed by its agent.
