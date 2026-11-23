# Shakedown 2026-11-18: `list` from the target, before 0.3.0

Status: needs-triage (what was fixed before the release is marked; what stays is listed below)

One wave of three Sonnet agents on the wheel 0.3.0 built from the branch `worktree-list-from-target`, narrowed
to what the release changes: `rowvioli list` reads the source from the target where there is no `sources/`.
H1 as two machines (a definition machine without extras, a worker's machine without `sources/`), P4 Jonas with
the docs only, P18 security. Not run: H2, H4, P1, P3, P16, P20, P22, the reviewers. Not covered by any of the
three: `odbc` listing against a real driver, pgbouncer, a Python newer than 3.12, `work` as a service.
✓ = reproduced by the coordinating session or confirmed in the source; the rest are leads from one agent, and
a ticket that starts from one reproduces it first.

## What they found

| From | Finding | Where it went |
|---|---|---|
| H1 | `run <source>` for a source applied with an empty `tables` block says `<source> is no source` ✓ | fixed in 0.3.0: it has no tables, `list` prints them |
| P4 | After a source left the definition, `list` from the target still answers and `run` says `is no source` ✓ | fixed in 0.3.0: `run` says it is not in the definition any more |
| H1, P18 | `list` of a `file` source hides the missing directory: `No such file or directory: '***'` ✓ | fixed in 0.3.0: the path stays readable, as in a run |
| H1, P18 | A connection without the field its connector reads makes `list` print only `'url'` ✓ | fixed in 0.3.0 |
| P4 | Pasting the whole output of `list` below the old lines of a `tables` block: `Cannot overwrite a value` | documented in 0.3.0 (`docs/definition.md`): the output replaces the lines |
| P4 | In a checkout with `sources/` and without a driver, the secrets or a route, `list` fails with the driver's or the module's message and does not say that a worker's machine can list ✓ (`contract.py`) | documented in 0.3.0 (`docs/commands.md`); the messages are left |
| H1, P18 | An empty `sources/` directory wins over the target and answers `list` with `apply`'s words: `sources holds no source files (*.toml); applying it would disable every table` ✓ | documented in 0.3.0; the message is left |
| H1, P18 | A role without `SELECT` on `_rowvioli.meta` and `_rowvioli.sources` gets `could not begin COPY: ERROR: permission denied for table meta` | documented in 0.3.0 (`docs/operation.md`): `list` runs with the worker's role; the message is left |
| H1 | A key file with garbage or of the wrong length: `Incorrect padding`, with no path and no way out | left |
| H1, P4 | A connector without its extra: `No module named 'arrow_odbc'`, with no hint at `rowvioli[odbc]` ✓ | left |
| P18 | A source name that is not valid UTF-8 gives a traceback (`UnicodeEncodeError`), with no secret in it | left |
| P18 | An `@` written plainly in the password of a source's URL (not through a placeholder): the driver's message shows the part after it. Same on the definition path and in 0.2.x | left; `docs/connections.md` calls the scrub best effort |
| P4 | `key new` in the definition's repository puts `worker.key` next to `worker.pub`, where it gets committed | left: a sentence and a `.gitignore` hint |
| P4 | A removed source keeps its sealed connection in the target, so its password stays usable to whoever holds the key | left: say it, or clear the connection when a source leaves |
| P4 | Nothing says that "every 15 minutes" is `max_age = "15m"` and a running `work` | left |

## Wishes

- **`list` prints only the tables the definition does not have yet** (P4). Task: add three new tables of a
  source that has eight. Workaround: replace the whole block, about four lines of shell, and carry the
  settings over by hand. Elsewhere: schema discovery that shows the difference (dlt, Airbyte). Status:
  unlisted.

## What held up

- The whole flow on two machines, on Python 3.11 without extras and 3.12 with them: `key new`, a source with
  an empty `tables` block, `apply --init`, `list` on the worker's machine, paste, `apply`, `run`. Mirrors
  equal to the source: a composite key, a table without a key, names with capitals; the view is not listed.
- `list` on the worker's machine with no source secret in its environment, and with exactly the worker's
  grants.
- One clear line and exit code 1 for: an unknown source, an unreachable target, a wrong password, a target
  without `_rowvioli`, no target address; a key file that is missing, a directory, unreadable, of another
  pair, a `.pub` file.
- No password in any output (P18, H1): refused connections, a wrong password, a wrong database, TLS, a
  malformed port or URL, passwords with `@ / : [ ] { } ; %` and spaces; the target's password too.
- A source name with quotes, `;`, `%`, a newline or 100 KB is a bound parameter. A ciphertext copied to
  another source is refused, a changed `type` gives a clean error, an unknown `type` loads nothing, a
  `key_id` the key file lacks is refused. `list` writes nothing to the target and leaves nothing behind.
- With `sources/` here: `--definition`, a directory that does not exist, a source file in a subfolder
  (0.2.2), a target name given twice; no key and no target address needed.
- The sentences about `list` in the README and under `docs/` were true on the hosts.

## Cleaning up

One image had been pulled (`python:3.11-slim`) and is removed; no container, volume or network was left.
