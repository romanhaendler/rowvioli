# 06: Documents and decisions

**Blocked by:** 01, 02, 03, 04, 05

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/shakedown/spec.md`. Findings and repros: `.scratch/shakedown/*.md`. Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes against PostgreSQL in Docker, no import of the program. Spec "Testing Decisions" apply; each finding's repro is the first red test. Unconfirmed findings (no ✓) are reproduced first and dropped if they do not go red.

## What to build

Spec stories 10, 40–49 and "Documents and decisions". Documents only. Every example copied from what this branch really prints.

- README: GRANT statements after the rights table; moment query with explicit offset and the sentence on moments before the first load; TLS (`sslmode=verify-full`, `https` for REST); `file` connector's DuckDB options (`sep`, `decimal_separator`, `nullstr`) and relative `path` resolved against the worker's working directory; type-tightened column in "What a person does by hand"; web UI section → one sentence; measurements section → pointer; old behaviour updated (zero rows, REST timeout, default key, scrubbing).
- `docs/package.md`: file tree and name checklist go; trademark search a line in open points; "Dependencies" heading stays.
- Connector guide: opening links decision 38; install section shows a connector beside an installed wheel.
- `docs/decisions.md`: eighth round "after the shakedown": options narrow and never move a connection; zero rows protects a mirror (refines 18); `max_seconds` the one bound.
- `docs/open-points.md`: scrubbing limit updated; empty-page end of REST paging; `run` before `key new` (json and multi-dim arrays are done in 02).

## Acceptance criteria

- [ ] No sentence still states behaviour changed by 01–05.
- [ ] `test_guide.py` and the package test stay green.

## Comments
