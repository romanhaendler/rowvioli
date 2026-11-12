# 09: `rowvioli list`

**Blocked by:** 08

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli list <source>` reads the definition and the environment, opens the source's connection, calls the connector's `tables` and prints TOML ready to paste into the source's `tables` block. `postgres` lists its tables with their primary keys; `file` lists its files without keys. A connector without `tables` fails with a clear message.

- [ ] `list` for `postgres` and `file` prints TOML that, pasted into a definition, applies and loads (spec test 17)
- [ ] A connector without `tables` fails with a clear message
