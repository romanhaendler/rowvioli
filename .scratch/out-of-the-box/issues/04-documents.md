# 04: The documents: the start, the commands, the connectors, decisions, changelog

**Blocked by:** 01, 02, 03

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/out-of-the-box/spec.md`. Source: the `## Comments` of tickets 01 to 03 and their diffs.

## What to build

- `README.md`: the start at the top becomes `key new`, `apply --init`, `work`, `status` with one variable; the
  commands table and its notes (defaults, the key file message, the type); the `rest` and `file` sections
  (`rows`, JSON, a pattern). Say each thing once.
- `examples/quickstart/compose.yaml`: the same short start.
- `docs/decisions.md`: decision 44 (names that are always the same are defaults; `apply --init` creates no key,
  with the owner's reason) and 45 (a near miss of a built-in type fails `apply`, refining decision 14).
- `docs/open-points.md`: remove what is built or fixed, add the new known limits from the comments.
- `CHANGELOG.md`: a section `Unreleased`. `GLOSSARY.md` only if a term is new.
- No version change.

## Acceptance criteria

- [ ] Every command line in the README's start works as written in a fresh directory (try it).
- [ ] `tests/test_guide.py` and the quickstart (`docker compose up` in `examples/quickstart`, then `down -v --rmi local`) pass.

## Comments
