# 03: The documents say the same thing about time

**Blocked by:** None (can start immediately)

**Status:** resolved

Spec: `.scratch/load-times/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program.

## What to build

Spec section "The decision is adapted": decision 36 in `docs/decisions.md` and every correction listed there for `docs/decisions.md`, `docs/open-points.md`, `GLOSSARY.md` and `README.md`. Documents only, no code. The measure (spec, "Further Notes"): the README needs one sentence for load times and points to the request for every consequence. Say next to `at` that a load after an event in the source is a request, not a load time.

Found while checking the spec against the documents, part of this ticket:

- `README.md`, section on `apply`: "A deployment triggers no load" is no longer the whole truth. A changed `at` or `max_age` takes effect with the next query (spec story 21, 22).
- `README.md`, target schema listing: `tables` gets `at` and `timezone` in its first (definition) line; schema version 2 wherever version 1 is named as current (also `docs/open-points.md`, "Schema versions").
- `README.md`, settings: `at` and `timezone` are names of rowvioli now, so a connector cannot have options of these names.
- `docs/open-points.md`: "A table that stays broken ... once per `max_age` after that" gets "and at each load time".
- `docs/package.md`: mention only if it lists the settings.

## Acceptance criteria

- [ ] `grep -rn "cannot be said\|No fixed times" README.md GLOSSARY.md docs/` finds only history ("Changes of the second round", "Not examined") or the corrected wording.
- [ ] Decision 36 has Decision, Why, Price, Rejected as in the spec.
- [ ] README: settings table, facts table, due formula, state diagram, table of situations, overview "what can be done from where" all carry the load time.

## Comments

Resolved on branch `load-times` (36e9759). Review fixes (ec757a4): the due formula is the cascade again with the load time as the one addition; decision 23 keeps its text and is marked as changed by decision 36.
