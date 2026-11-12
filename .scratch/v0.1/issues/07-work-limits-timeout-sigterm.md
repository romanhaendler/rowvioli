# 07: `work`: limits, `max_seconds`, SIGTERM, unreachable target

**Blocked by:** 03

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** `rowvioli work [--slots N]` is the worker loop without the end. It starts a run process only when something is claimable, with the same counts as the claim (decision 34), so that at most `parallel` per source and `max_running` in total load across all workers and full limits cost no processes. It identifies itself by host name and process id. It enforces `max_seconds` (source or table): it kills the run's process and records the reason on the table and the run through its own connection if the run is still `running`. On SIGTERM it starts nothing new, waits for its runs and exits 0 (decision 33). When its own connection fails it waits two seconds and connects again (decides open point E11; record it in `docs/open-points.md`).

- [ ] The prototype's `test_work` suite passes
- [ ] `work` on SIGTERM while a run is held lets the run publish, starts nothing new and exits 0 (spec test 9)
- [ ] With the limits full, the target's connections stay at the running tables plus one per worker over many polling intervals (spec test 10)
- [ ] A worker survives an unreachable target and loads again once it accepts connections (spec test 11)
- [ ] Table-level `max_seconds` overrides the source's (spec test 13)
