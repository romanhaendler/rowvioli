# 02: The `rest` connector

**Blocked by:** None (can start immediately)

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/connectors/spec.md`. Prior art: `src/rowvioli/connectors/file.py`, `tests/test_file.py`, `tests/test_secrets.py`, `tests/test_list.py`. Tests: the existing seam (`tests/conftest.py`), real processes, no import of the program.

## What to build

Spec stories 23 to 36 and the implementation decisions under "The `rest` connector".

- `src/rowvioli/connectors/rest.py` with `read` only, registered in the entry point group; the extra `rest` with httpx; the extra joins the development dependencies.
- Check the licence of httpx on PyPI and correct its row in `docs/package.md` if needed (spec "Further Notes").
- Nothing the spec lists under "Nothing else" or "Out of Scope".

## Acceptance criteria

- [ ] Spec "What is tested" 5 to 10, against an HTTP server inside the test (standard library, a thread) that records its requests. No container for the source, no network.
- [ ] The token appears in no reason and no line.
- [ ] The existing tests pass unchanged.
- [ ] No documents except the row in `docs/package.md` (ticket 04).

## Comments

Resolved on branch `connectors`, from con-02 (c85f93d). Review fixes: 8ce4756.
