# Shakedown 2026-11-17: the second run

Status: resolved (what was fixed is in the commit after it; what stays is listed under "Left as it is")

The rerun the spec asks for (`spec.md`, last note), before the release of 0.1.0. Wheel 0.1.0, one wave of
the same six Sonnet agents: H1, H2, P1, P4, P18, P27. Not run again: H4, P3, P16, P20, P22, P23, P24. Beside
it ran the first CI on GitHub and the review on Opus. ✓ = reproduced by the coordinating session, in CI, or
confirmed in the source; the rest are leads from one agent.

## Compared with the first run

| First run | Now |
|---|---|
| A REST token can be sent to another host (`security.md` 1) | fixed: nine ways tried, the other server saw no request, a 302 is not followed |
| `json`/`jsonb` fail on every later run (`source-data.md` 1) | fixed |
| `inet`, `xml`, ranges as `bytea`, `money` as cents (`source-data.md` 2) | fixed; `money[]` still arrives as `text[]` without the `$` |
| A typo in a setting goes to the connector (`first-use.md` 1) | fixed for `max_agee`, `logg`; ✓ `keys`, `logs`, `max_ages` passed through the plural exemption |
| A secret with a trailing newline in the status view (`security.md` 2) | fixed |
| A `file` source reads `../outside.csv` | fixed, also for a symlink and an absolute path |
| `apply` of a directory without source files, `worker.pub`, a missing key column, a mistyped `type`, `{"tables": {}}` during a pause | fixed; a mistyped `type` still shows only at the run, now with the installed types |
| No SQL for the rights, `CREATE` on the database, the user name masked in target errors (`install-target.md`) | fixed: the README's GRANT lines work as written on Postgres 15 and 18 |
| Traceback and paths in a reason | ✓ came back differently, see 1 |
| A multi-dimensional array is flattened, an empty REST page in the middle | still there, known limits |
| Short values scrubbed inside words | still there, known limit |

## What the rerun found

1. ✓ **A reason can be a fragment or the wrapper only.** A numeric `NaN` or one beyond 38 digits gave `pya` or
   `pyarrow.lib.`: ADBC cuts its message at about 1 KB and the rule took the traceback's last line. A wrong
   ODBC password gave `ODBC emitted an error calling 'SQLDriverConnect':`, which was also the one red test of
   the first CI run. An error while a statement executes kept `Failed to execute query '<sql>':` (review).
2. ✓ **The tests did not start on Python 3.11**: an f-string in `tests/test_status.py` that needs 3.12 (CI).
3. ✓ **`keys = ["id"]` mirrors a table without its key**, silently (P1, review).
4. ✓ **A custom connector's `columns = ["ab", "cd"]` is turned into a dict** (review).
5. ✓ **The README's custom connector breaks decisions 41 to 43** and fails on an empty first page; the guide
   did not say that a connector must yield at least one batch (P4, review).
6. ✓ **A token outside ASCII tells one of its characters** in the reason (P18).
7. ✓ **A tag publishes without the tests**, and the publish job could not check out a private repo (P18, review).
8. ✓ **A raw `@` in the password of `ROWVIOLI_TARGET_URL`** gives `could not translate host name`; the README
   did not say to percent-encode there (P1).

## Left as it is

- **Dependency floors are what the tests ran against** (`pyarrow>=26`, `adbc-driver-postgresql>=1.13`). H1 ran
  the postgres path with pyarrow 19.0.1, adbc 1.9.0 and pynacl 1.5.0; pyarrow 17 and adbc 1.7 fail, the second
  silently with zero rows. `duckdb>=2` is needed. Lowering a floor needs the suite on it.
- **Behind PgBouncer in transaction mode a run hung** after `relation "_stage" already exists` and left run
  processes behind (H1, a lead). The check exists (`target.py`) and an idle pooler passes it, as the known
  limit says; the hang is new and not reproduced.
- **`timestamptz 'infinity'`** fails with `Error occurred writing COPY data:` and no cause; the driver gives none.
  Now a known limit.
- **Every value of a connection is scrubbed, also `path = "csv"`** of a `file` source. Now part of the known limit.
- **A REST column absent from every row of one page** fails the run. Now a known limit.
- Leads, not reproduced: a ragged CSV names the wrong cause (`has no column id; it has: id,name`), a CSV with
  an unterminated quote loads two rows without an error, a composite type fails with the driver's text, a
  NUL byte in a file's name gives `embedded null character`, `rowvioli key new --help` prints the help of
  `key`, `run` prints `{"tables": {}}` after a changed `target_table` until the table is due, the guide's
  `uv tool install ./wheel --with` line has no form for extras, the `odbc` extra cannot be imported on a slim
  image without `libodbc`.
- **Wishes**, unchanged: a glob for files, wrapped REST answers (`spec.md`, "Out of Scope").
- **P27**: no command, flag, extra or entry point is unused. `apply --key` and `__main__.py` stay. The repo
  ships `.scratch/`, `docs/agents/` and `CLAUDE.md` on purpose: the decisions link into them.

## What held up

No half state anywhere: a failed first load left no table, a failed later run kept the old mirror. Names with
capitals, spaces, quotes, umlauts and keywords, 300 columns, NULL and duplicate keys. The first mirror in under
a minute from the README alone; four of five requests of a coding agent from README and guide alone. The wheel
on Python 3.11 to 3.14, arm64 and amd64; `twine check`; the wheel and sdist hold the package and nothing else.

## Lessons for the procedure

- Reports name the absence of a thing they did not find (`no pooler check anywhere`); the source said otherwise.
- P27 read and ran nothing. A reviewer's brief should say which tools must run.
- Cost: six agents, about 500k subagent tokens, 13 minutes wall clock for the slowest (H1).
