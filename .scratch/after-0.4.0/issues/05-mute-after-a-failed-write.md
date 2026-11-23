# 05: A worker stays mute after one failed write to stderr

**Status:** resolved

**Model:** Opus

From the final review of 0.4.0.

## What to build

`out()` in `src/rowvioli/work.py` sets `sys.stderr = None` after any failed write, so that a broken pipe does not turn the exit code into 120 at shutdown. A failure that passes (ENOSPC on `2>>worker.log`, a descriptor another process set non-blocking, a log stream that breaks once) then silences the worker for good, and a later crash prints no traceback. 0.3.1 crashed there and systemd restarted it with a fresh stderr.

Decide and build the smallest rule that keeps both promises: the exit code of `run` is never changed by output, and a worker does not go silent for good over a failure that passes. Candidates: give up only on `BrokenPipeError`, `ValueError` and a missing stderr; or drop the unflushed data and try again at the next line. Say in decision 52 (Price) what remains.

## Acceptance criteria

- [ ] The broken-pipe test stays green (exit code unchanged).
- [ ] A test with a write that fails once and then works: the next line is written.

## Comments

`out()` writes the encoded line to the stream below Python's buffer and keeps `sys.stderr`, so a failed line is lost instead of left to fail again at shutdown (exit code 120), and the next line is tried again; measured with a pipe without a reader (exit 0, a naive write gives 120) and a pipe set non-blocking and filled, then drained (`second` arrives, before only the buffered `first` at exit). Not checked: ENOSPC on a real file (`/dev/full`), and the Windows console, where the stream below is `_WindowsConsoleIO`, which takes UTF-8.
