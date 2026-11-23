# Shakedown 2026-11-23: the lines, before 0.4.0

Status: needs-triage (what was fixed before the release is marked; what stays is listed below)

One wave of three Sonnet agents on the wheel 0.4.0 built from the branch `worker-lines`, narrowed to what the
release changes: the lines of `run` and `work` on stderr and the status line at a terminal (decision 52).
After this run the owner removed the status line before the release; what was found about it is kept below.
H1 in a Linux container (`python:3.12-slim`, `docker logs`), H4 operation on the Mac through pseudo-terminals,
P18 security. Not run: H2, P1, P3, P4, P16, P20, P22, the reviewers. Not covered by any of the three: Windows
and its legacy console, a real systemd journal, the `⚠` line in a container, a real terminal emulator's reflow
after a resize, the extras (`file`, `odbc`, `rest`) in the container.
✓ = reproduced by a test that was red before its fix, or confirmed in the source by the coordinating session;
the rest are leads from one agent, and a ticket that starts from one reproduces it first.

## What they found

| From | Finding | Where it went |
|---|---|---|
| P18 | A target table name with control characters is written raw into the status line ten times a second: it clears the screen, floods it and sets the window title ✓ | gone: the status line was removed before the release; the filter it brought, control characters written as `?`, stays for the lines (next two rows) |
| P18 | A `\n` in a target table name forges a line in the log, e.g. a `✔ … ok` for another table; in 0.3.1 too, but the columns make it look genuine ✓ | fixed in 0.4.0, same filter |
| P18 | A reason that quotes source data carries ESC and `\r` to the terminal and the log; same in 0.3.1 ✓ | fixed in 0.4.0 for the lines; the reason in `runs.reason`, `rowvioli status` and the JSON on stdout stays raw: left |
| H4 | A terminal that stops reading (Ctrl+S, a pty nobody reads) froze the worker after about 5 s: nothing claimed, `max_seconds = 15` enforced after 47 s ✓ | gone: the status line was removed before the release, and with it the writer thread that fixed this; without the status line a terminal that stops reading holds the worker once its buffer is full of lines, as a pipe does and as in 0.3.1 |
| H1 | `docker run -t -d`: Docker holds the status line back and delivers it as one prefix of the next line, about 14 KB per idle minute | gone: the status line was removed before the release |
| H1 | `NO_COLOR=0` switches the colour off; the pages named only `NO_COLOR=1` ✓ (`colour()`) | documented in 0.4.0 |
| review | `rowvioli status` prints `reason` raw to stdout, and `list` and the target's error reach stderr raw (`cli.py`): the same route for escape codes ✓ (source) | left |
| P18 | `apply` accepts control characters in `target_table` and `target_schema` | left: the root of the first two findings |
| H4 | Ctrl+C at a terminal ends `work` and `run` with a 20-line `KeyboardInterrupt` traceback; no line for the runs, their rows stay `running` until a claim closes them ✓ (`loop` handles SIGTERM and SIGBREAK only) | left |
| H4 | The log says once that the target is unreachable and never that it is back ✓ (`loop`) | left |
| H4 | A terminal that reports 0 columns gets a status line cut at 79 ✓ (`width()`) | gone: the status line was removed before the release |
| H4 | Under cron with the working directory `/`, `run` fails with `the key file /worker.key: No such file`; clear, but the cron row of `docs/operation.md` does not say it | left |
| H1 | Once, a worker stopped about 3 s after a request wrote no `▶` and `✔` line although the table loaded; not seen again in two more runs, and H4's SIGTERM runs were clean | left: a lead, not reproduced |

## What held up

- `docker logs` without a terminal: marks, columns, the words, dim time, green and red; no `\r`, no spinner.
- `NO_COLOR=1`, `TERM=dumb`, `JOURNAL_STREAM` equal to stderr's device and inode: plain lines; another value: colour.
- No `LANG`, `LANG=C`, `LANG=POSIX`, `PYTHONIOENCODING=latin-1` or `ascii`: no crash, no lost line, exit 0.
- stderr closed, to a file, to a pipe whose reader left: the documented exit codes, and the load happens.
- SIGTERM: `stopping, N runs finish` once, exit 0 after the runs; SIGKILL: no orphan run processes, `worker lost`.
- Secrets: passwords with `@`, `/`, `[`, `%`, spaces and an escape sequence stayed scrubbed in every line.
- The example lines in `README.md`, `docs/operation.md` and `docs/loading.md` equal the wheel's output column by column.

Four more checks held up for the status line, which was removed before the release: none in the background and
painting again after `fg`, wiped on every way out, `+N` right at 80 and 40 columns, 0.4 % CPU idle at a terminal.

## Cost

Three Sonnet agents, about 30 minutes. Images pulled: none. Every container with the label
`rowvioli-shakedown` was removed by its agent.
