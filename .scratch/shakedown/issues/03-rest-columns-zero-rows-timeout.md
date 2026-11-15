# 03: What arrives: REST columns, zero rows, no REST timeout

**Blocked by:** 01

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/shakedown/spec.md`. Findings and repros: `.scratch/shakedown/*.md`. Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes against PostgreSQL in Docker, no import of the program. Spec "Testing Decisions" apply; each finding's repro is the first red test. Unconfirmed findings (no ✓) are reproduced first and dropped if they do not go red.

## What to build

Spec stories 15–19, 39 and the decisions under "What arrives" for REST and zero rows.

- A column named in `columns` absent as a key from every object of an answer page fails the run naming the column; present-with-null stays null.
- REST mirror columns follow the order of `columns`.
- Zero-rows limit (decision 18) applies only when the mirror exists and holds rows; first load or empty mirror publishes zero rows. `max_delete_share` untouched.
- The REST connector sets no request timeout; `max_seconds` bounds the run.
- Remove the duplicate test in `test_rest.py` ("cannot list tables"); `test_list.py` keeps it covered.

## Acceptance criteria

- [ ] Renamed field → run fails naming the column; mirror kept.
- [ ] A new empty source table is mirrored as an empty table; a mirror with rows whose source suddenly delivers zero rows still fails.
- [ ] A REST answer slower than the old timeout but within `max_seconds` loads.

## Comments

Resolved on branch `shakedown-fixes`, from sd-03 (c75d3ab, 1a72fc4). Review fixes: e97674d.
