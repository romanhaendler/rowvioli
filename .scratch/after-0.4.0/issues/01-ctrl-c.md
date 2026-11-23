# 01: Ctrl+C ends `work` and `run` with one line, not a traceback

**Status:** ready-for-agent

**Model:** Sonnet

From `.scratch/shakedown/fifth-run.md` (H4). Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes.

## What to build

Ctrl+C (SIGINT) at a terminal ends `rowvioli work` and `rowvioli run` with a 20-line `KeyboardInterrupt` traceback. The run processes are in the same process group and get the signal too; no line says what happened to them.

- On SIGINT the worker writes one line (`stopped by Ctrl+C, N runs ended`), makes sure its run processes are gone, and exits with 130. No traceback.
- The tables of the ended runs are closed as they are after SIGKILL of a worker (`worker lost`, decision 7); nothing new is recorded.
- SIGTERM keeps its meaning (decision 33): start nothing new, let the runs finish.
- `docs/operation.md` says what Ctrl+C does next to what SIGTERM does.

## Acceptance criteria

- [ ] A test sends SIGINT to a worker with a run going: exit code 130, the line on stderr, no `Traceback`, no run process left.
- [ ] The same for `run`.
