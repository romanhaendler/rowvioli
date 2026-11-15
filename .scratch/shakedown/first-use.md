# Shakedown 2026-11-15: first use

Status: needs-triage

From P1 (Lena, beginner: 25 s from install to the first mirror) and P4 (Jonas, a coding agent on README,
connector guide and `--help` only: four of five requests worked).

## Findings

1. ✓ **[Trap] A typo in a table or source setting is silently a connector option.** `max_agee = "5m"` or
   `logg = false` passes `apply --check`; the table runs with the default (`definition.py:95`). documented:
   README:172. Idea: the built-in connectors name their options, and anything else fails `apply` with the
   nearest known name.
2. ✓ **[Trap] `apply` looks for `worker.pub` in the current directory** (`cli.py:24`), while the README says
   "next to the definition". `rowvioli apply def/sources` from a repo root fails. Idea: look next to the directory.
3. ✓ **[Trap] `apply` of a directory without `*.toml` succeeds and disables every table** (`applied 0 sources`,
   exit 0). documented: "undone by applying the right one". Idea: fail on an empty definition.
4. **[Trap] After a fixed failure, `run` prints `{"tables": {}}` with exit 0**: the table waits out its pause
   and nothing says so (P1, H1). Idea: one stderr line "n tables wait until HH:MM; `run <source>` loads now".
5. ✓ **[Trap] The README's moment query uses a timestamp without zone** (README:434), read in the session's
   zone; and a moment before the first load returns 0 rows without a word. Idea: an offset in the example and one sentence.
6. ✓ **[Trap] The `file` connector's options go to DuckDB's reader, but only its docstring says so.**
   `decimal_separator = ","` for a European CSV is not findable from the README. Also no recipe for a type
   change after the first load, and a relative `path` is resolved against the worker's directory.
7. **[Trap] A key column that does not exist** shows `column "idd" does not exist ... SELECT 1 FROM _stage`.
   Idea: check the key against the source's columns and list them.
8. **[Trap] `type = "postgress"` passes `apply`** and fails at run time with "not installed on worker", which
   blames the install. Idea: name the installed types in the message.
9. **[Misfit, minor]** `run shop orders` does not suggest `public.orders`; a duplicate or NULL key names no
   example value; missing variables are named one at a time; `init` and `key new` print nothing on success;
   a wrong source password passes `apply` (documented); the connector guide assumes a checkout and `uv tool`;
   REST columns arrive in no stated order; no glob for daily files.

## What held up

- The quickstart, `max_age` messages ("1 hour", `3600`, "1x"), `key = "id"`, TOML syntax errors with line and column, a missing `$VAR`, `status` before `init`, `key new` refusing to overwrite.
- A password `p@ss/w:rd` raw in the environment.
- The SQLite connector from the guide in about 30 lines; `list` found its key. History "now" and a minute ago were right.
