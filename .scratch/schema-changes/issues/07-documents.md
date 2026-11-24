# 07: Documents and the new decision

**Blocked by:** 06

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/schema-changes/spec.md` (it holds where the other papers differ). Cases: `cases.md`, reasons: `strategy.md`, Postgres behaviour: `facts.sql`, prototype: `experiments/09_schema_changes.sql`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program; see the spec's "Testing Decisions".

## What to build

Stage 6 of the spec: implementation decisions 25 to 27, story 48, and the known limits from "Further Notes" into `docs/open-points.md`. Describe what the program on this branch does; where it differs from the spec, say so in a comment here instead of documenting the spec.

Also `CHANGELOG` in the manner of its existing entries.

## Acceptance criteria

- [ ] Glossary, the new decision with the "Changed by decision …" notes on 17, 31, 40, 49, `docs/loading.md`, `target.md`, `definition.md`, `connector-guide.md`, `operation.md`, `open-points.md`.
- [ ] `tests/test_guide.py` and the like keep the examples true (spec "What is tested" 6).
- [ ] No change of the program.

## Comments
