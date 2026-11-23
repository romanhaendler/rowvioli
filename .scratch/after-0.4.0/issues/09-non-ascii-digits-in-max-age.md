# 09: `max_age = "1٣h"` passes the check and fails with the database's message

**Status:** ready-for-agent

**Model:** Sonnet

From `.scratch/shakedown/sixth-run.md` (P24). Confirmed in the source: `interval()` in `definition.py` matches with `\d`, which takes any Unicode digit, so `apply` ends with `invalid input syntax for type interval`. The check for `at` uses `\d` too.

- Only ASCII digits pass; the message is the one every other wrong `max_age` gets. Test first, with an Arabic-Indic and a full-width digit, for `max_age` and for `at`. Look for other `\d` and `\w` in `src/` that check input.
