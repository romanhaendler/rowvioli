# 10: Shipping: quickstart, examples, release, benchmark

**Blocked by:** 03

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `examples/quickstart`: a compose file with a source Postgres, a target Postgres and a container that runs `init`, `key new`, `apply` and `run` against one source file, so that `docker compose up` ends with a loaded mirror and a status view to look at; its own CI job. `examples/definition`: the template for the definition repository from README "Operation", with a pipeline running `apply --check` on merge requests and `apply` after a merge. `examples/Dockerfile`: the program plus a place for the operator's drivers. A release workflow publishing to PyPI from a tag through trusted publishing. `bench/`: one script reproducing the README's measurement table at 10⁶ rows. README corrections that 0.1 forces (for example the first example using `odbc`).

- [x] `docker compose up` in `examples/quickstart` ends with a loaded mirror, as a separate CI job (spec test 21), leaving no volumes behind
- [x] `examples/definition`, `examples/Dockerfile` and the release workflow exist and match the README
- [x] `bench/` reproduces the measurement table's columns at 10⁶ rows

## Comments

- The quickstart's last service `status` prints the status view and five mirror rows; `docker compose up` then keeps the databases running until Ctrl-C, so a newcomer can look around. The CI job therefore runs `docker compose up -d` (fails if the load fails) and `docker compose wait status`, then `down -v --rmi local`. `up --exit-code-from` does not fit: it aborts on the first container that exits.
- `examples/Dockerfile` installs `PACKAGE` (default `rowvioli` from PyPI) with the build context bind-mounted at `/src`; the quickstart passes `PACKAGE=/src` to build this checkout. A whitelist `.dockerignore` at the repo root keeps the context to the package.
- `examples/definition` has no `worker.pub` and no `uv.lock`: a real key cannot be shipped, and the lock needs `rowvioli` on PyPI. `pyproject.toml` says to run `uv lock` and `rowvioli key new` once; `.gitignore` keeps `worker.key` out. The pipeline is GitLab CI, because the README speaks of merge requests.
- `bench/bench.py` times the program's own statements with `pg_stat_statements` in one container (2 CPUs, 4 GB). Filling includes reading the source through the connector, so it is not the in-memory client of experiment 8. "Compare and publish in one transaction (earlier variant)" is not the program's path and is not measured. First run at 10⁶ rows: compare unchanged 1.9 s, diff at 1 % 1.3 s, publish at 1 % 0.3 s, keyless replace 1.6 s, fill 4.5 s, publish initial load 3.7 s; a whole run 6 to 10 s. README numbers left as they are.
