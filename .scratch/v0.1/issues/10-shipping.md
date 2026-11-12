# 10: Shipping: quickstart, examples, release, benchmark

**Blocked by:** 03

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `examples/quickstart`: a compose file with a source Postgres, a target Postgres and a container that runs `init`, `key new`, `apply` and `run` against one source file, so that `docker compose up` ends with a loaded mirror and a status view to look at; its own CI job. `examples/definition`: the template for the definition repository from README "Operation", with a pipeline running `apply --check` on merge requests and `apply` after a merge. `examples/Dockerfile`: the program plus a place for the operator's drivers. A release workflow publishing to PyPI from a tag through trusted publishing. `bench/`: one script reproducing the README's measurement table at 10⁶ rows. README corrections that 0.1 forces (for example the first example using `odbc`).

- [ ] `docker compose up` in `examples/quickstart` ends with a loaded mirror, as a separate CI job (spec test 21), leaving no volumes behind
- [ ] `examples/definition`, `examples/Dockerfile` and the release workflow exist and match the README
- [ ] `bench/` reproduces the measurement table's columns at 10⁶ rows
