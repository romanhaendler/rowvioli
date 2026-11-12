# 06: Crashes, pause, requests, progress

**Blocked by:** 03

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** A run killed at any step leaves the mirror unchanged and releases its lock; a dead run shows as `failed` with `worker lost` and is tried again after the pause (1, 2, 4, 8 minutes, never beyond one maximum age). Requests through `requested_at` behave as README "Loading now" says: several before a run cause one run, one during a run causes one more, one during a run that fails causes one more at once. A concurrent reader never sees an empty or half-loaded mirror. While a table is loading, the status view shows the rows written so far (from `pg_stat_progress_copy` of the lock holder's backend) and the rows of the last successful run, and nothing when that is not visible (decision 31).

- [ ] The prototype's `test_crashes` and `test_pause_requests` suites pass
- [ ] While a run is held filling, the status view shows rows written so far greater than zero (spec test 18)
