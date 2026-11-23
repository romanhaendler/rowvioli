# 06: The mascot test starts the worker as the foreground of a controlling terminal for nothing

**Status:** ready-for-agent

**Model:** Sonnet

From the final review of 0.4.0. `tests/test_work.py`, the mascot test: `start_new_session=True` and `preexec_fn` with `TIOCSCTTY` served only the foreground check of the status line that was removed before 0.4.0. The mascot needs `isatty()` only. Put the test back to the plain pseudo-terminal it had on 0.3.1, keeping the assertion that nothing moves the cursor, and drop the imports only it used.

## Acceptance criteria

- [ ] `uv run pytest tests/test_work.py` green; `fcntl` and `termios` imported only if something else needs them.
