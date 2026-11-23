# 05: A worker stays mute after one failed write to stderr

**Status:** ready-for-agent

**Model:** Opus

From the final review of 0.4.0.

## What to build

`out()` in `src/rowvioli/work.py` sets `sys.stderr = None` after any failed write, so that a broken pipe does not turn the exit code into 120 at shutdown. A failure that passes (ENOSPC on `2>>worker.log`, a descriptor another process set non-blocking, a log stream that breaks once) then silences the worker for good, and a later crash prints no traceback. 0.3.1 crashed there and systemd restarted it with a fresh stderr.

Decide and build the smallest rule that keeps both promises: the exit code of `run` is never changed by output, and a worker does not go silent for good over a failure that passes. Candidates: give up only on `BrokenPipeError`, `ValueError` and a missing stderr; or drop the unflushed data and try again at the next line. Say in decision 52 (Price) what remains.

## Acceptance criteria

- [ ] The broken-pipe test stays green (exit code unchanged).
- [ ] A test with a write that fails once and then works: the next line is written.
