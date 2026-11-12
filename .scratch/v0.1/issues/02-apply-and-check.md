# 02: `apply` and `apply --check`

**Blocked by:** 01

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli apply <dir>` reads the definition (TOML, several sources per file allowed, settings as in README "Defining a source"; any other key reaches the connector as an option), fills in `$NAME` placeholders only in the string values of the `connection` block (`$$` is a literal `$`), percent-encodes a placeholder that lands in the user-info part of a URL (decision 32), seals each connection with the public key (`--key`, default `worker.pub`) together with the source name, stores the `key_id` beside the ciphertext, and writes sources and tables by name in one transaction. It updates only the definition's columns, disables what is missing, re-enables what comes back with its old id, leaves `loaded_at`, `attempted_at`, `attempts`, `requested_at` untouched, and stores the hash of the definition in `meta`. It fails and changes nothing on a missing variable, duplicate target tables in a source, two sources sharing a `target_schema`, a missing public key, and a target without `_rowvioli` (message: run `rowvioli init` first). `apply --check <dir>` checks syntax, required settings, units, keys, duplicate target tables, shared target schemas and well-formed placeholders without a target and without the environment, never filling in a placeholder.

- [ ] The prototype's `test_apply` suite passes (adapted where 0.1 changes behaviour on purpose)
- [ ] `apply` against a target without `init` fails with the message to run `rowvioli init` first (spec test 2)
- [ ] `apply` fails when two sources share a `target_schema` (spec test 3)
- [ ] `apply --check` passes a valid definition and fails each invalid one, with no target reachable and no variable set (spec test 4)
- [ ] `apply` needs no source and no driver for it; the stored connection and the output contain no password
- [ ] `meta` holds the definition hash; a changed definition gives a different hash
