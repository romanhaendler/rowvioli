# 07: `work`: limits, `max_seconds`, SIGTERM, unreachable target

**Blocked by:** 03

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli work [--slots N]` is the worker loop without the end. It starts a run process only when something is claimable, with the same counts as the claim (decision 34), so that at most `parallel` per source and `max_running` in total load across all workers and full limits cost no processes. It identifies itself by host name and process id. It enforces `max_seconds` (source or table): it kills the run's process and records the reason on the table and the run through its own connection if the run is still `running`. On SIGTERM it starts nothing new, waits for its runs and exits 0 (decision 33). When its own connection fails it waits two seconds and connects again (decides open point E11; record it in `docs/open-points.md`).

- [x] The prototype's `test_work` suite passes
- [x] `work` on SIGTERM while a run is held lets the run publish, starts nothing new and exits 0 (spec test 9)
- [x] With the limits full, the target's connections stay at the running tables plus one per worker over many polling intervals (spec test 10)
- [x] A worker survives an unreachable target and loads again once it accepts connections (spec test 11)
- [x] Table-level `max_seconds` overrides the source's (spec test 13)

## Comments

- The worker loop (`src/rowvioli/work.py`) kills a run after `max_seconds` from its claim line and writes the reason `ended after max_seconds = N` on the run and the table in one statement, only if the run is still `running`. Reasons of killed runs wait in a list and are written on the next poll, also after a reconnect.
- Reconnect (E11, already recorded in `docs/open-points.md`): only a failing connection of a running `work` is retried. The first connect at start stays strict, so a wrong URL ends at once; `run` does not retry. The first failure is printed once to stderr.
- README: the systemd example gets `KillMode=mixed`. With systemd's default `control-group`, SIGTERM would reach the run processes too and end them, which breaks decision 33.
- Not built: decision 33's "killing it hard kills its runs too". A `kill -9` of `work` leaves its run processes running until they end; under systemd (`KillMode=mixed`) and in a container they die with the worker.
- Spec test 10 passed already with ticket 03's claimable count; the test fails when the worker ignores that count.
