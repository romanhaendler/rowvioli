# 16: What the second round found in the connectors and in `init`

**Blocked by:** 14

**Status:** claimed

**Model:** Opus

The second wave of the shakedown (host H2, 2026-11-24, wheel of c917551) through the connectors the first wave
did not use. Most of this is older than the branch (it is in 0.4.1 too); the owner wants no known fault left, so
it is fixed here. The scripts named are in the session's scratch directory under `shake/h2b/` (they may be gone;
each item says enough to build its red anew). Built beside ticket 15, which changes `load.py`
(`withheld`, `check`, `carry_out`, the locks): keep out of those; a change this ticket needs there is small and
said under Comments.

## What to build

1. **ODBC never stores another value than the source's without saying so** (`o_float.py`, through psqlODBC): a
   `float8` arrives as `real` (0.1234567890123456 becomes 0.12345679, 1e300 becomes Infinity); a date `infinity`
   and `-infinity` both become today's date; a timestamp `infinity` becomes 9999-12-31 23:59:59; `timestamptz`
   arrives as `timestamp`, `bool` as text. Find what is the connector's doing (how it reads the driver's
   description, `connectors/odbc.py`) and what is the driver's (psqlODBC's settings): what the connector can read
   right, it reads right (a double as `float8`); what a driver gives wrong and the connector cannot know is said in
   `docs/connectors.md` beside the other losses of a driver, with the setting of psqlODBC that avoids it where one
   exists. A value that silently becomes another one is the worst kind: where it can be told (a float column
   described with a precision of a double), it is right or the run fails naming the column.
2. **A timestamp the target's type cannot hold, read through ODBC, is not blamed on the target without a column**
   (`o1b.py`: 4713 BC or `-infinity` gives `SQLSTATE 22008 in the target …`): the reason names the column and says
   the way out, without the value.
3. **A Postgres source's `timestamp` or `timestamptz` of `infinity` loads, or fails with a reason that names the
   column and the way out** (`inf.py`: today the reason is only `Error occurred writing COPY data:`; `-infinity`
   and a date `infinity` load). Load it if the driver can be made to (the target holds `infinity`); otherwise the
   reason, as for a `numeric` beyond 38 digits (ticket 11 item 6, ticket 12 item 1).
4. **Excel**: a date cell arrives as its serial number (`46023`), a datetime as `46023.12783564815`, TRUE as `1`,
   and `columns = { d = "date" }` then stops with a way out that does not work (the file is right); an integer of
   19 digits loses digits (`1.234567890123457e+18`). Read what DuckDB's reader offers (the `excel` extension's
   options) and make a date a date and a large integer exact if it can; what cannot be, is said in
   `docs/connectors.md`, and the stop's way out for an Excel file says what works. (`x2.py`)
5. **A Parquet column of a type the target has none for** (a struct: `Can't map Arrow type 'struct'…` with the
   driver's C++ wrapper, no column, no way out): the reason names the column, its type and the way out; or it
   loads as `jsonb` if that is what the JSON reader of the same connector does with nested values (one rule for
   nested values of a file). (`l3.py`, `k_struct.parquet`)

### `init` (host U1, scripts under `shake/u1b/`; `src/rowvioli/target.py`)

6. **Two `init` at once** (init containers on several replicas): the loser exits 1 with Postgres's bare
   `column "program_version" of relation "runs" already exists`, or on an empty target
   `duplicate key value violates unique constraint "pg_namespace_nspname_index"` (the version is read outside the
   step's transaction and not again). The result was right 5 of 5 times; the loser should wait for the winner and
   end as an `init` on a ready target does (exit 0). The smallest that is right: take a lock first (an advisory
   lock in the transaction, or the version read again under the lock the step takes).
7. **A superuser `init` leaves the new objects with another owner than the older ones** (`columns`,
   `columns__log`, `columns__history` owned by postgres, the rest by the owner role): a later step run by the
   owner would fail on them. The new objects get the owner of `_rowvioli.runs`, in the step.
8. **`init` as a role that does not own the bookkeeping** says only `must be owner of table runs`: the reason
   names the owner role and that `init` runs as it or as a superuser (`docs/operation.md` says it; the message
   does not). `init` interrupted with Ctrl+C prints Postgres's bare `canceling statement due to user request`:
   say that nothing was changed.
9. `docs/operation.md`: a forgotten 0.4.1 worker writes "a dozen" lines a second; U1 saw about 4 this time and
   12 before: say "several"; and an old worker in the middle of a run finishes and publishes it after `init`
   (seen clean): say so. No way back to 0.4.1 after `init` is documented: say it (a dump before, restore).

### The target's session and the extras (host H1, scripts under `shake/h1b/`)

10. **A target database that is not UTF8 never stores another text than the source's.** In a LATIN1 target
    `Müller` is stored as `MÃ¼ller` with the run `ok` (the session never sets `client_encoding`, so libpq takes the
    database's; `SESSION` in `src/rowvioli/target.py`); with a non-ASCII schema name `rowvioli status` ends in a
    traceback (`UnicodeDecodeError`) and every run dies before its claim. `PGCLIENTENCODING=UTF8` cured it: the
    session sets it. A value the target's encoding has no character for then fails the run with the reason of
    SQLSTATE 22P05 (seen, no value in it). Test with a LATIN1 database in the suite's target.
11. **A connector whose extra is not installed says which to install**: `connector "file" cannot be loaded: No
    module named 'duckdb'` adds `pip install "rowvioli[file]"` (`odbc`, `rest` alike), in `list`, `run` and `work`.

## Acceptance criteria

- [ ] 1 to 11: a test each, seen red first, at the existing seam (`tests/odbc/run.sh` for ODBC); a sentence under
      Comments for any that cannot be tested there.
- [ ] `docs/connectors.md` and `CHANGELOG.md` say what changed; no new entry in `docs/open-points.md` (an
      inherent limit of a driver goes to `docs/connectors.md` and decision 55).
- [ ] The whole suite and `tests/odbc/run.sh` pass.

## Comments
