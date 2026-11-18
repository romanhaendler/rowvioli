# 02: REST: the option `rows` for a wrapped answer

**Blocked by:** none

**Status:** resolved

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

Built in `rest.py` and `tests/test_rest.py` only. `rows` is split at dots and walked through the answer's objects; the
result must be an array of flat objects, else the run fails with "<path> must answer a JSON array of flat objects in
the field <rows> (option rows)" (no value of the answer in it). Paging, the page-repeats check and the absent-column
check already worked on the extracted array, so they needed no change. Tests: wrapped and nested, paged and unpaged;
missing field, wrong depth, a bare array and a non-array field fail naming `rows` and keep the mirror.

For the documents (README "rest" section, open points):
- README: "`rows`: the field of the answer that holds the array of rows, one name or several joined by dots
  (`data`, `result.items`); without it the answer itself is the array. Paging ends when the array in the field is
  empty. An answer without the field, or with something else than an array of flat objects there, fails the run and
  names `rows`."
- Limit: a field whose own name contains a dot cannot be named. `apply` does not check `rows` (a non-text value
  fails at the run).
- Open points: remove the entry about wrapped REST answers.
