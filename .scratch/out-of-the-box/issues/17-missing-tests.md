# 17: Tests that would notice a broken promise

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet (each test is named; the one fix is a few lines)

From the test-quality audit of 2026-11-18 (`.scratch/shakedown/third-run.md`, "Test quality"). In each
place the program is right today and no test would notice if it stopped being right.

## Tests to add (through the `rv` fixture, as every test)

1. Sealed connection bound to its source: swap the `connection` values of two sources in
   `_rowvioli.sources`, a run fails with "sealed for another source".
2. A column name with `"` in it (a CSV header `a"b`) arrives in the target under that name.
3. A password from a variable with `@`, `/` and `:` in it: the run connects and loads.
4. `max_age = "0m"` and `"0h"` fail `apply`.
5. An unset variable: the message names the variable, no traceback.
6. A password with `'`, `\` and a newline does not show in the reason of a failed run.
7. `log = 1` and `parallel = true` fail `apply`; `key = [""]` fails `apply`.

## One fix

A literal password with `[` in a URL in the definition fails the run with `Invalid IPv6 URL`, because
`connection_values` in `load.py` calls `urlsplit` on it. The run should get as far as the connection, and
the password must still be scrubbed. Test first.

## Not in this ticket

Making the typo cases in `test_apply_mistakes.py` cheaper, and the five tests that take 58 of 208 s.
