# Shakedown 2026-11-25, before 0.5.1: the run lines in columns

Status: resolved (every finding is in 0.5.1 or declined below with its reason)

One host on Sonnet against the wheel `0.5.1`: H4 Operation, narrowed to what 0.5.1 changes, the lines `run` and
`work` write on stderr. It measured the columns by character position with a script. Not run: every other host and
persona, a run longer than an hour (`1h 3m` was seen in the unit test only), Windows.
✓ = reproduced by the coordinating session.

| From | Finding | Where it went |
|---|---|---|
| H4 ✓ | A target table name in wide (CJK) characters pushes its line's columns right by one cell per character: the padding counts characters, not cells. An umlaut stands right | declined for now: the `shortcut:` comment in `work.say_run` names it; the width comes from Postgres's `length()`, which counts characters too |
| H4 | The example block of `docs/operation.md` does not match the output | not a finding: the session printed the block's lines with the program's format strings and found them in the page character for character; the host compared lines with other counts |
| H4 | A longer table applied while `work` runs widens the column from the next line on; the lines before stay narrow | as documented ("as wide as the longest target table name in scope"); no line stood out of column within either block |
| H4 | A script that reads the lines by field breaks: `+1,000` is no integer, `1m 5s` is two fields, the table column varies | CHANGELOG 0.5.1 points such a script to `_rowvioli.runs` |
| H4 ✓ | A connection value of one character, a password `x`, is masked wherever it stands in a reason (`ma***_delete_share`); not new in 0.5.1 | declined: `scrub` replaces every value of the connection on purpose, and a password of one character is no real set-up |

What held up: names of 12, 28, 45 and 103 characters under `run --slots 3` and `work --slots 3` (61 lines at one
offset); a narrowed `run <source> <table>` takes the width of its scope; counts of 0, 999, 1,000, 123,456 and
1,000,000 with their separators, equal to `_rowvioli.runs`; a run of 65 s as `1m 5s` under `0.1s`; the reason of a
failure (`max_delete_share`, `max_seconds`) at the start of the counts; `NO_COLOR=1` without an escape byte, colour
in a file with the same visible columns; SIGTERM mid-run and a target cut off and back, as `docs/operation.md` shows.
