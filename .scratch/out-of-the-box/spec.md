# Out of the box: the first mirror needs nothing but the target's address

Status: ready-for-agent

From `docs/open-points.md` and `.scratch/shakedown/second-run.md` ("Left as it is"), 2026-11-17, after 0.1.0.

## Problem Statement

The first mirror takes two variables, five commands and a directory argument, and the two likeliest slips
on the way (no key file yet, a mistyped `type`) show only at the run, per table, in words that name no next
step. A typical API (`{"data": [...]}`), a JSON file and a file that lands daily under a new name each need a
connector of one's own.

## Solution

One sentence carries it: **the first mirror needs nothing but the target's address, and every slip on the
way names the next command.** No new concept, no change to the schema `_rowvioli` (there is no migration).

- **Names that are always the same need not be said.** `ROWVIOLI_KEY_FILE` falls back to `worker.key` in the
  current directory; `apply` without a directory takes `sources`, as `list` does. The start becomes
  `key new`, `apply --init`, `work`, `status`, with `ROWVIOLI_TARGET_URL` alone.
- **A missing key file stops `run` and `work` at the start**, names the path and says that `rowvioli key new`
  creates it. No table is attempted.
- **A `type` that is a near miss of a built-in connector fails `apply`** (`postgress`: did you mean
  `postgres`). Any other type passes as today: `apply` does not know the connectors (decision 14).
- **A REST answer may wrap its rows**: the option `rows` names the field that holds the array.
- **The `file` connector reads JSON and a pattern** (`orders_*.csv`), still only inside the connection's `path`.
- **`apply --init` does not create a key pair.** The owner refused it: a private key must not appear as a
  side effect where the definition is deployed.

Whoever has a working set-up sees no change.

## Implementation Decisions

- The key file default is resolved in one place and used by the start check and by the run.
- Near miss of a type: the rule of `definition.typos` (one edit under six letters, two from six), against
  `postgres`, `file`, `odbc`, `rest`. A connector of one's own must not be named one letter from a built-in.
- `rows`: a field name, or several joined by dots (`result.items`). Without it the answer is an array as today.
  Paging ends on an empty array inside the field. An answer without the field fails and names the option.
- A pattern is a table name with `*` or `?`. The connector expands it itself inside `path`, resolves every
  match and refuses one outside; no match fails the run. A table with a pattern needs `target_table`
  (`apply` says so), since a name cannot be derived from it.
- JSON: `.json`, `.jsonl`, `.ndjson` through DuckDB. What happens to nested values and to types is found out
  and measured by the ticket; a run is right or fails (decision 41 and the shakedown spec).
- Leads (no ✓) are reproduced first and dropped if they do not go red; the ticket's comment says which.

## Who implements

| Work | Model |
|---|---|
| 01 The start: defaults, key file, type, small messages | Sonnet. Specified; three small files. |
| 02 REST `rows` | Sonnet. One option in one connector. |
| 03 Files: JSON, pattern, the CSV leads | Opus. The confinement must hold for a pattern, and what DuckDB does with JSON has to be found out. |
| 04 Documents, quickstart, changelog, decisions | Sonnet. |
| 05 Review of the whole; P1 and P4 again on the wheel | Opus; the personas on Sonnet. |

## Testing Decisions

The existing seam only (`tests/conftest.py`, `rv`): real processes against PostgreSQL in Docker, no import of
the program; a test asserts what a person sees. Each change starts with its red test. The version in
`pyproject.toml` is not raised: a push of a raised version to main publishes.

Disk: `df -h .` and `docker system df` before and after. Never remove containers, volumes or images by a
broad filter and never prune: other agents run beside you.

## Out of Scope

The pooler (owner: later), dead runs as a view (schema change), reading from a timestamp on, `request`,
patterns for source tables, the web UI, migration, dependency floors, `apply --diff`, casting columns.
