# `apply`: definition, placeholders, sealed connections

Status: ready-for-agent
Blocked by: 01

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

Spec sections "Definition", "apply", "Connections" (sealing and opening, source name bound into the box). User stories 3-14, 42.

## Acceptance criteria

- [ ] Spec tests 1, 2, 3 pass.
- [ ] Spec test 4 as far as `apply` goes: a removed table is disabled, nothing is deleted.
- [ ] Spec test 20: a shortened maximum age changes `due_at` in `status` without a run.
- [ ] The stored connection does not contain the password (first part of spec test 18).
- [ ] `apply` needs no source database and no driver for it (user story 10).

## Comments

Deviations from README / GLOSSARY / decisions made by the implementation (impl-02):

- The option for the public key is `rowvioli apply <dir> --key <file>`, default `worker.pub` in the current directory. The README names no option.
- The sealed content is the JSON `{"name": <source>, "connection": <block>}`. Opening compares the name. `key_id` is the first 16 hex digits of the SHA-256 of the public key (as in experiment 7); nothing reads it yet.
- Spec test 1 compares every column except `sources.connection`: the ciphertext differs on every `apply`, as the README says ("Equal values look different").
- Placeholders are filled in only in the string values of the `connection` block, one level deep. A `$` followed by anything but an upper-case name or `$` stays as it is.
- Ignored without an error: `log`, table-level `max_delete_share` and `max_seconds`, and every other key (connector options). The README allows them; the spec puts them out of scope. `apply --check` would have to decide whether an unknown key is a typo.
- One file may hold several sources (every top-level table is one). The file name is not compared with the source name. The README says "one file per source" but does not say what happens otherwise.
- The tables of a removed source are disabled too, because they are no longer in the definition. Adding a source or table back enables it again with its old `id` and what the workers experienced.
- Duplicate target tables are checked within a source only. Two sources with the same `target_schema` could still collide; the README says a schema belongs to one source, nothing checks it.
- `INSERT ... ON CONFLICT` draws an identity value even when it updates, so ids of tables added later have gaps. They still start at 1 and stay stable per name.
