# Commands

Every command, what it needs, and what it says and returns.

| Command | Does | Needs |
|---|---|---|
| `rowvioli init` | Creates the schema `_rowvioli` in the target and says so: `the schema _rowvioli is ready in the target`. | target |
| `rowvioli key new` | Creates a key pair in the current directory: `worker.key` for the workers and `worker.pub` for the definition, and says so: `created worker.key (keep it secret) and worker.pub`. Overwrites neither. | nothing |
| `rowvioli list erp` | Prints the tables of a source with their keys, ready to paste into its `tables` block. Reads the source from the definition (`--definition <dir>`, or `sources/` here); where there is no `sources/`, from the target, as a worker would. | definition, environment, connector, source; or target, private key (`ROWVIOLI_KEY_FILE`, else `worker.key` here), connector, source applied |
| `rowvioli apply --check` | Reads the definition and checks it. Writes nothing. Meant for a laptop and for the pipeline of a merge request. | definition |
| `rowvioli apply` | Writes the definition into the target: one row per source and table, connections encrypted. Without a directory it takes `sources`, as `list` does. With `--init` it creates the schema `_rowvioli` first when it is missing. | definition, environment, `worker.pub` next to the directory (or `--key <file>`), target |
| `rowvioli status [erp [dbo.Customers]]` | Prints the enabled tables with their target name, age, due time, status and reason or progress, from the view `_rowvioli.status`. Names narrow it the way `run` takes them. Exits 0 whenever it could print the state. | target |
| `rowvioli work --slots 4` | Runs permanently and loads whatever is due, up to four tables at a time. | connectors, private key (`worker.key`), target |
| `rowvioli run` | Loads everything that is due, once, and ends. | connectors, private key (`worker.key`), target |
| `rowvioli run erp` | Requests all tables of `erp` and loads until nothing of `erp` is due. | connectors, private key (`worker.key`), target |
| `rowvioli run erp dbo.Customers` | The same for a single table, named as in the source. An unknown or disabled name fails and, when exactly one enabled table ends in the name, suggests it: `erp customers: no enabled table has this name; did you mean public.customers`. A first name that is no source fails and says so (``customers is no source: the first name of `run` is a source, the second a table; did you mean `rowvioli run erp customers` ``), when exactly one enabled table ends in it. | connectors, private key (`worker.key`), target |

`rowvioli apply --init` saves the extra `init` on a fresh target, and does nothing more when the schema exists. It needs what `init` needs, `CREATE` on the database, so a pipeline role with only the GRANT lines in [The target](operation.md#the-target) applies without the flag to a target that an admin has initialised, after `rowvioli init`. It creates no key pair: a private key must not appear as a side effect where the definition is deployed, so `apply` without `worker.pub` stops and says that `rowvioli key new` creates it (decision 44).

`rowvioli --version` prints the version of the installed package.

`list` takes the source from the definition when `--definition` is given or a `sources/` directory is here (an empty one too), and from the target otherwise. From a definition, this machine needs the connector, the source's secrets in the environment and a route to the source; where one is missing, run `list` on a worker's machine. From the target the connection is the one `apply` stored, decrypted with the private key, so the machine needs the connector and a route to the source but no checkout and no source secrets (the target address is there). A source is there once it has been applied, even with an empty `tables` block. A source removed from the definition keeps its row, so `list` still answers for it.

Naming something means "this, now". `run` without a name means "whatever is due". `run` takes `--slots` too.

When `run` without a name loads nothing because tables wait out the pause after a failure, it says so on stderr, so that `{"tables": {}}` does not look broken. The answer on stdout and the exit code stay as they are:

```
2026-11-15 14:44:49 1 table waits out its pause after a failure, the first until 14:45:49; `rowvioli run <source>` loads them now
```

Every command that needs the target finds it in `ROWVIOLI_TARGET_URL`. A password with `@`, `/` or `:` must be percent-encoded there (`@` is `%40`), because this address is written by hand, unlike a source's connection, which `apply` encodes. A worker finds its private key through `ROWVIOLI_KEY_FILE`, and in `worker.key` in the current directory without it. `run`, `work` and `status` check what they need at start and name what is missing, for example `ROWVIOLI_TARGET_URL is not set`. A target address with a second `@` after the scheme fails before any connection (`ROWVIOLI_TARGET_URL has more than one @ after the scheme: a password with @, / or : must be percent-encoded`) and shows no part of the address. `run` and `work` also stop at the start when the key file cannot be opened, before any table is attempted. A missing one is named with its path and the way out; a directory or an unreadable file gives the system's reason:

```
the key file /srv/etl/worker.key: No such file or directory; copy worker.key from where `rowvioli key new` was run (only for a new target does `rowvioli key new` create it)
```

`apply` in detail:

- **Idempotent.** Applying the same definition twice gives the same state. Sources and tables are created or updated by name.
- **It never touches what the workers experienced.** `loaded_at`, `attempted_at`, `attempts`, `reason` and `requested_at` stay as they are. A deployment by itself triggers no load and loses no request. A changed `max_age` or `at` takes effect with the next query: a table that is due by the new values is loaded. A table that is new in the definition has never been attempted and is therefore due at once. One exception: a table whose target schema or table changes gets `attempted_at`, `attempts`, `reason` and `loaded_at` reset, because under the new name no mirror exists yet: status shows no age and no old reason, it is due at once as a new table is, and a first failure pauses one minute. `requested_at` stays (decision 46).
- **The definition is always the whole.** `apply` gets a directory, `sources` unless it is given another; the source files in its subfolders belong to it too (a symbolic link to a folder is not followed). What is no longer in it is disabled, never deleted, and its target tables stay, but it holds no name any more: the definition alone says who owns a name. Whoever takes the name over meets the checks before publishing on the first run. Applying the wrong directory by mistake is undone by applying the right one.
- **Disabling is the only way to stop a table.** Until then it is loaded and retried. A run that is loading the table when it is disabled finishes.
- **It fails rather than guess.** On a missing variable (all of them named at once), a setting that is one or two letters from one of rowvioli's own (two neighbouring letters swapped count as one edit; for a setting under six letters it is one letter), a directory with no source file, a `type` that is a near miss of a built-in connector that no installed connector bears (`type fiel is not installed here; did you mean file?`), `apply` with no `sources` directory (it names the directory it looked in and says that `rowvioli apply <directory>` takes another), a `file` pattern without `target_table`, a missing public key (the message names the path it tried and says that `rowvioli key new` creates it), a target name given twice (`list` fails the same way when it reads a definition, see [Defining a source](definition.md)), or a target without the schema `_rowvioli` (then it says: run `rowvioli init` first). A misspelt setting does not reach the connector as an option, and an empty directory would disable everything:

  ```
  erp.toml: erp: max_agee is not a setting; did you mean max_age? (other keys go to the connector as options)
  empty/ holds no source files (*.toml); applying it would disable every table
  ```
- **It says a changed name.** For every table that is already in the target and gets another target name, `apply` prints one line, after it has written the definition. A table that was disabled and comes back under another name gets it too:

  ```
  erp: dbo.customers: target name changes from raw_erp.customers to raw_erp.clients; the old tables (raw_erp.customers, its __log and __history) stay where they are
  ```

  Nothing in the target is renamed or dropped ([what a person does by hand](loading.md#what-a-person-does-by-hand)).
- **One transaction.** If anything fails, nothing changes.

Answer of `run` on stdout:

```json
{"seconds": 41.2,
 "tables": {
  "raw_erp.customers": {"status": "ok", "inserted": 12, "updated": 3, "deleted": 1},
  "raw_erp.suppliers": {"status": "failed", "reason": "62 % of the rows would be deleted"}}}
```

| Exit code | Meaning |
|---|---|
| 0 | No table failed. |
| 1 | At least one table failed. The other tables are published. |
