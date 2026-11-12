# 01: What rowvioli may ship

**Blocked by:** None (can start immediately)

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/connectors/spec.md`. Behaviour reference: `README.md`, `docs/decisions.md`, `docs/package.md` ("Dependencies").

## What to build

Spec stories 1 to 10 and the implementation decisions under "What rowvioli may ship".

- Decision 38 appended to `docs/decisions.md` in the form of its neighbours: the carrying sentence, the four consequences, what was rejected, "the project's rule, not legal advice".
- A paragraph "Licences" under "Connectors" in the README: the carrying sentence and its three consequences, and that vendor drivers are installed by the operator under the vendor's licence (story 7).
- One test: every dependency of the core and of every extra in `pyproject.toml` has a row in the dependency table of `docs/package.md`. It checks that the row exists, not the licence.

## Acceptance criteria

- [ ] Spec "What is tested" 11. The test fails when a dependency is added to the project file without a row (try it, then undo).
- [ ] The existing tests pass unchanged.
- [ ] No other part of the README, no version change (ticket 04). No connector code.

## Comments

Resolved on branch `connectors`, from con-01 (5d343cf). Review fixes: 8ce4756.
