# 02: What arrives: the postgres connector's types

**Blocked by:** none

**Status:** resolved

**Model:** Opus

Spec: `.scratch/shakedown/spec.md`. Findings and repros: `.scratch/shakedown/*.md`. Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes against PostgreSQL in Docker, no import of the program. Spec "Testing Decisions" apply; each finding's repro is the first red test. Unconfirmed findings (no ✓) are reproduced first and dropped if they do not go red.

## What to build

Spec stories 11–14 and the decision "The postgres connector chooses per column what it reads". Find out and measure which types the driver carries faithfully; do not touch those.

- `json`/`jsonb` → `jsonb`; `money` → `numeric`; any other type the driver would deliver as binary (not `bytea`) → `text`.
- Still streams in chunks, never holds a table.
- An existing `json` mirror meets the schema check on its next run; the reason names the column.

## Acceptance criteria

- [ ] A source with `json`, `jsonb`, `inet`, `xml`, `timetz`, a range, `bit`, `point`, `tsvector`, `money` loads twice and the mirror equals the source (as text where the spec says text).
- [ ] `bytea`, arrays, `uuid`, timestamps, intervals arrive unchanged (existing tests stay green).
- [ ] `docs/open-points.md`: "Column types without equality" loses `json`; known limit for multi-dimensional arrays.

## Comments

Resolved on branch `shakedown-fixes`, from sd-02 (66c8de2). Review fixes: e97674d.
