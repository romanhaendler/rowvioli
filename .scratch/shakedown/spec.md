# After the shakedown: a run is right or fails, and says why where the mistake was made

Status: ready-for-agent

Findings: `.scratch/shakedown/` (run of 2026-11-15, wheel 0.2.0). Every finding there is taken up below, as a
change or under "Out of Scope" with its reason.

## Problem Statement

The first shakedown put the wheel into the hands of a beginner, a coding agent, a security reviewer and
hostile data. The model held: no half state, no stray table, no injection through names, the old mirror kept
on every failure. But it failed people in three ways.

**A secret can go where its connection does not say.** A REST source's token is sent to `url + path`, and
`path` is an option, stored in plain text in the target. Whoever can write `_rowvioli.tables` can append
`.evil.com/x` and receive the token, which breaks the README's promise that writing to the target cannot
point a password at another server. A `file` source reads `../outside.csv` as readily as a file in its
directory. And a token with a trailing newline, which every Docker secret read from a file has, reaches the
status view, `runs.reason` and the worker log in clear text, because a driver prints it as a repr and the
scrubber looks only for the literal value.

**What arrives is not always what the source holds, and the run says `ok`.** `inet`, `xml`, `timetz`,
ranges and other types the driver cannot name arrive as raw bytes in `bytea`; `money` arrives as cents in a
`bigint`. `json` and `jsonb` load once and then fail on every later run with `operator does not exist: json
= json`, so the table stays at its first state. A REST API that renames a field empties the column, and the
run counts it as `updated`.

**A mistake is not named where it is made.** A typo in a setting (`max_agee = "5m"`) passes `apply --check`
and is silently handed to the connector as an option; the table runs with the default. `apply` of a
directory without source files disables every table and exits 0. `apply` looks for `worker.pub` in the
current directory although the README puts it next to the definition. A key column that does not exist ends
in `column "idd" does not exist ... SELECT 1 FROM _stage`. A mistyped `type` blames the worker's install.
After a failure is fixed, `run` prints `{"tables": {}}` and nothing says the table waits out its pause.
Driver errors reach the reason with their wrapper, a traceback and absolute paths. Behind a pooler in
transaction mode, runs share TEMP tables and leave locks held, with no word about the pooler.

Besides, the documents promise or repeat more than they should: a web UI that is not built, measurements
copied from `docs/measurements.md`, a rights table without the SQL, a moment query without a time zone, and
no word on TLS or on the DuckDB options of the `file` connector.

## Solution

One sentence carries it: **a run is right or it fails, and every failure is said where the mistake was
made, in words a person can act on.**

- **A connection's address is complete.** Options can narrow where a connector reads inside its source,
  never move it to another one. A REST `path` is a path on the connection's host; a `file` table is a file
  inside the connection's `path`. Anything else fails the run and names the option.
- **A secret is scrubbed in every form a driver may print it**, and only secrets are scrubbed from the
  target's errors, so the user name and host stay readable there.
- **What the driver cannot carry arrives as text, not as bytes.** `json` and `jsonb` arrive as `jsonb`,
  `money` as `numeric`, every other type the driver would deliver as bytes as `text`. A REST column the
  definition names and the answer no longer has fails the run.
- **`apply` names what it can know**: a setting it nearly recognises, a directory without source files, the
  public key it looked for. A run names what only the run can know: a key column the source does not have, a
  connector type that is not installed among those that are, a pooler that shares the connection.
- **A reason is one line**: the driver's message without its wrapper, traceback or paths.
- **The zero-rows limit protects a mirror; it does not forbid an empty first load.** A source that delivers
  zero rows fails only when the mirror has rows.
- **One bound for a run: `max_seconds`.** The REST connector has no timeout of its own.
- **The documents say less and say it once**, and add the four things people looked for.

Whoever has a working set-up sees no change, except that runs which were silently wrong now fail or arrive
readable, and that a `json` mirror (which could never load a second time) has to be dropped by hand once.

## User Stories

### Secrets

1. As an owner of the target, I want a REST source's token to go only to the host named in its encrypted connection, so that someone who can write `_rowvioli.tables` cannot collect it.
2. As an owner of the target, I want a run whose `path` would leave the connection's host to fail and name `path`, so that a tampered option shows instead of acting.
3. As a definition author, I want `apply` to reject a REST `path` that does not start with `/`, so that I learn the rule before a run.
4. As an owner of the target, I want a `file` table to be readable only inside its connection's `path`, so that a table name cannot reach any file the worker can read.
5. As an operator, I want a `file` table named `../x.csv` or with an absolute path to fail with a reason that names the table, so that I see what was attempted.
6. As an operator whose secrets come from files, I want a token with a trailing newline never to appear in the status view, the runs, the log or the JSON of `run`, so that a common set-up does not leak.
7. As a security reviewer, I want a secret scrubbed as written, stripped of surrounding whitespace and in its escaped (repr) form, so that a driver that quotes a value does not get it past the scrubber.
8. As an operator, I want an error from the target to show its user and host and hide only the password, so that I can find the likeliest typo myself.
9. As a person reading the status view, I want a REST type mismatch to name the column and the expected type without the source value, so that data does not end up in reasons and logs.
10. As an operator, I want the README to say how to require TLS for the target and for Postgres sources, so that a connection does not fall back to plain text unnoticed.

### What arrives

11. As a consumer, I want `json` and `jsonb` columns to arrive as `jsonb`, so that the table loads on every run, not only on the first.
12. As a consumer, I want an `inet`, `xml`, `timetz`, range, `bit`, `point` or `tsvector` column to arrive as readable text, so that I can use the value without decoding bytes.
13. As a consumer, I want a `money` column to arrive as `numeric` with its amount, so that `$12.50` does not become `1250`.
14. As a consumer, I want `bytea`, arrays, `uuid`, timestamps, intervals and every type that arrives correctly today to arrive unchanged, so that the fix costs me nothing.
15. As an operator, I want a REST column named in `columns` that is absent from every row of an answer to fail the run and name the column, so that a renamed field does not empty my mirror.
16. As an operator, I want a field that is present with a null value to stay a null, so that real nulls are not failures.
17. As a data engineer, I want a new source table that is empty to be mirrored as an empty table, so that it does not wait for its first row.
18. As a data engineer, I want a source that suddenly delivers zero rows for a mirror that has rows to still fail, so that a broken source cannot empty a mirror.
19. As an operator, I want a slow REST API to be bounded only by `max_seconds`, like every other source, so that I do not meet a hidden five-second limit.

### Mistakes named where they are made

20. As a beginner, I want `apply --check` to fail on `max_agee` and say "did you mean `max_age`", so that a typo does not silently keep the default.
21. As a beginner, I want the same for every setting rowvioli owns, at a source and at a table, so that `logg`, `timzone` or `targt_table` are caught too.
22. As a connector author, I want an option whose name is not close to a rowvioli setting to pass to my connector as today, so that my options keep working.
23. As an operator, I want `apply` of a directory without source files to fail and say that it would disable every table, so that a wrong path in CI does not switch everything off.
24. As a pipeline author, I want `apply sources/` to find `worker.pub` next to `sources/`, as the README draws the definition, so that it works from the repository root.
25. As a pipeline author, I want a missing public key to be reported with the path that was tried, so that I can see where it looked.
26. As a pipeline author, I want `--key` to keep working for a key kept elsewhere, so that existing pipelines do not break.
27. As a beginner, I want a key column the source does not have to fail with "table X has no column idd; it has: id, v", so that I can fix the definition without reading SQL.
28. As a beginner, I want a mistyped `type` to fail with the connector types installed on the worker, so that I see it is my spelling and not the install.
29. As an operator, I want a connector that is installed but cannot load (a missing system library such as unixODBC) to report its import error, so that I know what to install.
30. As a beginner, I want `run` to say on stderr that tables are waiting out their pause, until when, and that `run <source>` loads them now, so that an empty answer after a fix does not look broken.
31. As a beginner, I want `run shop orders` to suggest `public.orders` when that is the one enabled table it could mean, so that I learn the naming.
32. As a beginner, I want `run`, `work` and `status` to name every missing environment variable at once, so that I fix them in one go.
33. As a beginner, I want `init` and `key new` to print one line on success saying what they created, so that I know they worked.
34. As a definition author, I want the message for a reserved column name to say when `log = false` is the way out, so that I am not told there is none.
35. As an operator, I want every reason to be one line, the driver's own message without its wrapper (`NOT_FOUND: Failed to prepare query:`, `IO:`, `nanoarrow call failed`), traceback or file paths, so that the status view stays readable.
36. As an operator, I want a run whose driver message is empty to say so, naming the step, instead of ending in a colon.
37. As an operator, I want a control connection that goes through a pooler in transaction mode to fail at once with "use session mode", so that runs never share TEMP tables or leave locks held.
38. As an operator with a pre-created schema, I want a worker without `CREATE` on the database to load into it, so that I can grant only what the schema needs.
39. As a consumer of a REST mirror, I want its columns in the order `columns` names them, so that the table reads as I declared it.

### Documents

40. As an operator, I want the README's rights table followed by the GRANT statements per role, so that I do not find them by trial.
41. As a consumer, I want the moment query in the README written with an explicit offset and a sentence that a moment before the first load returns nothing, so that I get the right rows in my time zone.
42. As a CSV user, I want the README to say that the `file` connector's other options go to DuckDB's reader, with `sep`, `decimal_separator` and `nullstr` as examples, so that a European CSV is one option away.
43. As an operator, I want the README to say that a relative `path` of a `file` source is resolved against the worker's working directory, so that systemd and cron set-ups work.
44. As an operator, I want "What a person does by hand" to cover a column whose type I tightened after the first load, so that I know which tables to drop.
45. As a reader, I want the README not to describe a web UI that does not exist, so that I do not look for it.
46. As a maintainer, I want the measurements in one place, so that two copies cannot drift.
47. As a maintainer, I want `docs/package.md` and the connector guide not to repeat the file tree, the name checklist and decision 38, so that there is less to keep true.
48. As a connector author installing from a wheel, I want the connector guide to show how to install my connector beside the wheel, so that I do not need a checkout.
49. As a maintainer, I want the decisions to record why options cannot move a connection, why zero rows protects only a mirror, and why `max_seconds` is the only bound, so that the next person does not undo them.

## Implementation Decisions

### Secrets

- **The REST connector joins `path` to the connection's URL and checks the result.** `path` must start with `/`; the joined URL must keep the scheme, host and port of the connection's URL. Otherwise the run fails with a reason that names the option and not the URL. The check is in the connector, because a writer of the target bypasses `apply`; `apply` repeats the `/` rule for the built-in `rest` type so that the definition author learns it first.
- **The `file` connector resolves the file and refuses it unless it lies inside the resolved `path`.** Absolute table names and `..` fail the run.
- **The scrubber scrubs each value in three forms**: as written, stripped of surrounding whitespace, and escaped as Python's repr writes it inside quotes. The existing written-and-decoded forms of a URL or ODBC password stay. For source connections, every value of the connection stays a secret (decision 26: the connection is encrypted as a whole, the address too).
- **For the target, only the password of `ROWVIOLI_TARGET_URL` is scrubbed**, as the README already says for the worker's line about an unreachable target. Every command uses the same rule.
- **The REST connector's type mismatch** names table, column and expected type; it no longer echoes the value.

### What arrives

- **The postgres connector chooses per column what it reads**, from the type the driver reports in the field metadata (it already does so for `numeric`). `json` and `jsonb` are read as `jsonb`; `money` as `numeric`; any column the driver would deliver as binary while its source type is not `bytea` is read as `text`. Types that round-trip today are not touched. The way to do it (a first look at the schema and a select list with casts, or a cast of the delivered column) is the implementer's, as long as the connector still streams in chunks and never holds a table.
- **An existing mirror with a `json` column** meets the schema check ("changed its type") on its next run. That is accepted: such a mirror could never load a second time anyway. The reason names the column and the README's recipe applies.
- **The REST connector fails a run** when a column named in `columns` is absent as a key from every object of an answer page. A key present with `null` stays a null. The REST mirror's columns follow the order of `columns`.
- **The zero-rows limit** (decision 18) applies only when the mirror exists and holds rows. A first load, or a mirror that is empty, publishes zero rows. `max_delete_share` is untouched.
- **The REST connector sets no request timeout.** `max_seconds` bounds the run, as for every source. A new decision records it.

### Mistakes named where they are made

- **`apply` (and `apply --check`) fails on a key that is not a rowvioli setting but is one or two edits away from one**, at source and table level, and names the setting. Other unknown keys pass to the connector as today. No connector has to declare its options for this.
- **`apply` fails when the directory holds no source file**, naming the directory and saying that applying it would disable every table.
- **The default public key is `worker.pub` in the parent of the directory `apply` gets**, which is where the README's layout puts it. When it is missing, the message names the path that was tried. `--key` stays and gets a test.
- **A run checks the key against the columns of the first chunk** before it fills the staging table, and fails naming the missing columns and the ones there are.
- **A connector type that is not installed** gets a message that lists the installed types. A connector that is installed and fails to import reports its import error.
- **`run` without names**, when nothing was loaded and tables of the definition wait out a pause, writes one stderr line: how many wait, the earliest moment one is due, and `rowvioli run <source>` to load now. The JSON on stdout and the exit code do not change.
- **`run <source> <name>`** with an unknown name suggests the one enabled table whose name ends in `.<name>`, if there is exactly one.
- **The checks of the environment** name every missing variable in one message.
- **`init` and `key new`** print one line saying what they created.
- **The reserved-name message** says `log = false` frees `_run`, `_loaded_at`, `_valid_from` and `_valid_to`, and that `_op` cannot be freed.
- **A reason is the first line of the driver's message**, with the known wrapper prefixes of ADBC and nanoarrow removed, no traceback and no absolute path. An empty message becomes "the driver gave no message" with the step. The cut happens once, where the reason is stored, so the status view, the runs, the log line and the JSON agree.
- **The control connection checks that it is a session of its own**: it reads `pg_backend_pid()` in two transactions; if the two differ, the command fails with "a connection pooler in transaction mode is in front of the target; use session mode". It is done once per control connection and once per command that opens the target.
- **A run creates its schema only if it does not exist**, so a worker needs `CREATE` on the database only for schemas it has to create.

### Documents and decisions

- README: the GRANT statements after the rights table; the moment query with an explicit offset and the sentence on moments before the first load; TLS (`sslmode=verify-full` in the target's and a Postgres source's URL, `https` for REST); the DuckDB options and the relative `path` of the `file` connector; the type-change case in "What a person does by hand"; the web UI section reduced to one sentence ("everything a UI needs is in `_rowvioli`"); the measurements section reduced to the pointer; the rules above where the README states the old behaviour (zero rows, REST timeout, the default key, scrubbing).
- `docs/package.md`: the file tree and the name checklist go; the trademark search stays as a line in open points. The "Dependencies" heading stays, a test reads it.
- The connector guide: its opening links decision 38 instead of restating it; the install section shows how to put a connector beside an installed wheel.
- `docs/decisions.md`, an eighth round "after the shakedown": a decision that options narrow a connection and never move it; a decision that the zero-rows limit protects a mirror (refining 18); a decision that `max_seconds` is the one bound of a run.
- `docs/open-points.md`: "Column types without equality" loses `json`; the scrubbing limit names what is now covered; a known limit for multi-dimensional arrays; the empty-page end of REST paging; `run` before `key new`.
- `GLOSSARY.md`: no new term.

### Who implements

Before implementing a ticket, decide which model it needs, and take the smallest that fits (CLAUDE.md).

| Work | Model |
|---|---|
| Secrets: REST path, file confinement, scrubbing, the target's password | Sonnet. Specified; the care goes into the tests with a hostile server. |
| What arrives: the postgres connector's types | Opus. Which types the driver carries faithfully has to be found out and measured. |
| What arrives: REST columns, zero rows, no REST timeout | Sonnet. |
| Mistakes named: `apply`, run messages, the reason line, the pooler check, the schema | Sonnet. |
| Documents and decisions | Sonnet. |
| Review of the whole at the end | Opus. |

## Testing Decisions

- **One seam, the existing one**: the program as a real process against PostgreSQL in Docker (`rv` fixture). Tests never import the program. The REST tests keep their local HTTP server (now also one that receives a redirected request and asserts it never arrives); the file tests keep their temporary directories.
- **A good test asserts what a person sees**: the exit code, the reason in the status view, the line on stderr, the rows of the mirror compared with the source. Not how a function scrubs or casts.
- **Each finding's red is the first test.** The repros are in the shakedown's notes: a token with `\n`; `path = ".evil.com/x"` with a listening second server; a table `../outside.csv`; a source with `json`, `jsonb`, `inet`, `xml`, `money` loaded twice and compared; a REST answer with a renamed field; an empty new source table; `max_agee`; an empty directory to `apply`; `apply sources/` from the parent with `worker.pub` there; a key `idd`; `type = "postgress"`; `run` after a fixed failure; a reason from a driver error.
- **Prior art**: secrets in `test_secrets.py` and `test_apply.py` (no password in output or target); checks in `test_checks.py`; REST in `test_rest.py`; files in `test_file.py`; messages of `run` in `test_run.py` and `test_status_command.py`.
- **The pooler check** is tested without pgbouncer: a test that the check passes on a direct connection is enough in the suite; the transaction-mode case is measured once by hand (pgbouncer in Docker) and recorded in `docs/measurements.md`.
- **The duplicate test** (`test_rest.py`, "cannot list tables") goes; `test_list.py` keeps the line covered.
- Disk: check `df -h .` and `docker system df` before and after; remove the containers and volumes the tests created.

## Out of Scope

- **Casting or skipping a column in the definition** (wish). rowvioli is not a transformation tool; the way out is a view in the source, and the shakedown found that it holds.
- **A glob for files and wrapped REST answers** (wishes). A connector of one's own covers them (decision 27); a glob may come later.
- **`apply --diff`** (wish). `apply` already prints changed names; a diff of the whole definition is a tool of its own.
- **Multi-dimensional arrays.** Rare; recorded as a known limit.
- **An empty page in the middle of REST paging.** It is how paging ends; the delete limit catches a large cut. Recorded as a known limit.
- **Example key values in the messages for duplicate or null keys.** They would put source data into reasons, which this spec removes elsewhere.
- **Checking a source password at `apply`.** `apply` has no route to a source (decision 14).
- **Short passwords scrubbed inside words.** Only a one- or two-character secret does this; not worth a rule.
- **The ODBC connector's types.** Not measured; a later shakedown with a real driver.
- **Removing the mascot or `experiments/`.** Both are decisions with a reason (37, the measurements).
- **The entries that did not run** (H4, P3, P16, P20, P22, P23, P24): a later shakedown.

## Further Notes

- The findings with ✓ in `.scratch/shakedown/` were reproduced or confirmed in the source by the coordinating session; the others are leads from one agent. A ticket that starts from an unconfirmed finding reproduces it first and drops it if it does not go red.
- The rule "a run is right or fails" was already the design; this spec closes the places where the driver, a connector or a message slipped past it. No new concept, two small decisions and one refinement.
- After the tickets are done, the shakedown is run again with the same six entries and compared (procedure step 6).
