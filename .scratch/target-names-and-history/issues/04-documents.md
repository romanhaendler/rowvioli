# 04: The documents and the two decisions

**Blocked by:** 01, 02, 03

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/target-names-and-history/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program. Disk: check `df -h .` and `docker system df` before and after; remove the containers and volumes your tests created.

## What to build

Spec stories 36 to 40 and the implementation decisions "Two new decisions" and "Documents", and the known limits from "Further Notes" into `docs/open-points.md`. Documents only, no code. Section 13 of `docs/measurements.md` exists (03); the README follows its recommendation on an index and a faster query.

- Every example is copied from what the commands on this branch really print or what SQL really returns (run them), not from the spec.

## Acceptance criteria

- [ ] The measure of the spec ("Further Notes"): "a schema belongs to exactly one source" is replaced by "the definition gives no target name twice"; history needs one paragraph, one invariant and one query.
- [ ] Every failure reason of this spec has its statement in the one place that says what a person does by hand.
- [ ] Decision 35 is marked as changed; no sentence in README, GLOSSARY or `docs/` still states the old rule, the 58-byte limit, or that the history view is unverified.
