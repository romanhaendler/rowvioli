# 13: Options a connector does not know fail, an emptied source may publish, a dead run is closed

**Blocked by:** none

**Status:** resolved

**Model:** Sonnet

From the shakedown of 2026-11-17 (P22, P16, P3, P20, H4), decided by the owner on 2026-11-17. The project is
in version 0: behaviour may change where it is better afterwards, and so may the schema `_rowvioli` (raise
`SCHEMA_VERSION` in `target.py` and the number in `sql/schema.sql` and its tests together; there is no
migration yet, which is accepted).

## What to build

- **An option a shipped connector does not know fails the run and names the option and those it knows.**
  Today `postgres` ignores every option (`incremental = "updated"`, `query = "select ..."` load the whole
  table), and `odbc` and `rest` ignore unknown ones; `file` already fails (its options are DuckDB's). A
  connector of one's own decides for itself; the connector guide says that it should do the same.
- **A source that delivers zero rows publishes when the table says `max_delete_share = 1.0`.** No new
  setting: who allows every row to be deleted allows an empty table. Without it, decision 42 stands (zero rows
  fail when the mirror has rows). The reason for zero rows names this way out.
- **The `path` of a `file` connection stays readable in reasons**: `no such file in ***` hides the one word a
  person needs. A directory is not a secret. Every other value of a connection is scrubbed as before; say in
  the code why `path` is the exception.
- **A dead run is closed.** Its row in `_rowvioli.runs` stays `running` without `finished_at` for ever,
  while the table shows `failed: worker lost`. The run that next claims the table (or whatever is the
  smallest place that already notices the dead run) sets the dead run's row to failed with the reason
  `worker lost` and a `finished_at`. Find out where the table's `failed: worker lost` comes from and close
  the row there. A schema change is allowed if it is the smaller solution; prefer none.
- **Consumers may read the status** (documents only): the README's GRANT lines for the consumer role get
  `USAGE` on `_rowvioli` and `SELECT` on `_rowvioli.status`, after you have tried that such a role can read
  the view and nothing else in the schema, and the sentence that this is how a reader tells a quiet source
  from a worker that is gone.

Documents for all of it: README (connectors, checks before publishing, failures, the rights), a decision in
`docs/decisions.md` for the options (47) and one refining 42 for zero rows, `docs/open-points.md` ("Seeing
dead runs" goes, the scrubbing limit loses its `path` example), `docs/connector-guide.md`, `CHANGELOG.md`.

## Acceptance criteria

- [ ] `incremental = "updated"` on a `postgres` table fails its run and names `incremental`; the same for an unknown option of `odbc` and `rest`; every option the README documents still works.
- [ ] An emptied source table with `max_delete_share = 1.0` gives an empty mirror and `D` rows in the log; without it the run fails and the reason names `max_delete_share`.
- [ ] A missing file's reason shows the directory; a password or token never shows.
- [ ] After a run killed with `kill -9`, the next run of that table leaves no row in `runs` that is `running` without a live run.
- [ ] The whole suite is green.

## Comments

Resolved. Options are refused in the connector (`contract.known_options`, one message form for `postgres`, `odbc`, `rest`); the `odbc` refusal is untested here (no driver). Zero rows: `check` in `load.stage` also needs `max_delete_share < 1`; decisions 47 (options, `path`) and 48 (zero rows, refining 42). `path` is exempt in `connection_values` only for `type = "file"`, its URL password is still scrubbed. The dead run: the status view derives `worker lost` from the missing lock (nobody writes it), so the claim, under the table lock, closes any `running` row of that table. No schema change. Consumer rights tried with a role holding only the README's two lines: it reads `status`, and `tables`, `runs`, `meta`, `sources` are denied. In the tests the source password is `x`, so a reason shows `ma***_delete_share`: the tests match `_delete_share = 1.0`.
