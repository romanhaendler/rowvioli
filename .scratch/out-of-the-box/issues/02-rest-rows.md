# 02: REST: the option `rows` for a wrapped answer

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/out-of-the-box/spec.md` (read it first, also "Testing Decisions"). Behaviour reference: `README.md`, `docs/decisions.md`. Tests: `tests/conftest.py`, `rv` fixture. Documents are ticket 04: change no `.md` outside your ticket file, but list under `## Comments` every sentence the documents need.

## What to build

In `src/rowvioli/connectors/rest.py`: the option `rows` names the field of the answer that holds the array of
rows, one name or several joined by dots (`data`, `result.items`). Without it nothing changes. With it:
an answer that is no object, lacks the field or holds no array of flat objects there fails and names `rows`;
paging ends on an empty array in the field; the page-repeats check and the absent-column check work on the rows.
No value of the answer enters a reason.

## Acceptance criteria

- [ ] `{"data": [...]}` with `rows = "data"` and `{"result": {"items": [...]}}` with `rows = "result.items"` mirror, paged and unpaged.
- [ ] A missing field fails with the old mirror kept.
- [ ] The whole suite is green.

## Comments
