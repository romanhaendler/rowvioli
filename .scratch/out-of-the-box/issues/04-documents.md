# 04: The documents: the start, the commands, the connectors, decisions, changelog

**Blocked by:** 01, 02, 03

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/out-of-the-box/spec.md`. Source: the `## Comments` of tickets 01 to 03 and their diffs.

## What to build

- `README.md`: the start at the top becomes `key new`, `apply --init`, `work`, `status` with one variable; the
  commands table and its notes (defaults, the key file message, the type); the `rest` and `file` sections
  (`rows`, JSON, a pattern). Say each thing once.
- `examples/quickstart/compose.yaml`: the same short start.
- `docs/decisions.md`: decision 44 (names that are always the same are defaults; `apply --init` creates no key,
  with the owner's reason) and 45 (a near miss of a built-in type fails `apply`, refining decision 22).
- `docs/open-points.md`: remove what is built or fixed, add the new known limits from the comments.
- `CHANGELOG.md`: a section `Unreleased`. `GLOSSARY.md` only if a term is new.
- No version change.

## Acceptance criteria

- [ ] Every command line in the README's start works as written in a fresh directory (try it).
- [ ] `tests/test_guide.py` and the quickstart (`docker compose up` in `examples/quickstart`, then `down -v --rmi local`) pass.

## Comments

2026-11-17, Sonnet. Every command and message quoted was run against Postgres 16 with the code of this branch.

Changed:
- `README.md`: the start at the top (`key new`, `apply --init`, `work`, `status`); "Defining a source" (near-miss type); "Where the keys live"; "Commands" (table, `--init` paragraph, key file and missing-variable paragraph, "`apply` in detail": the exception for `attempted_at`, default directory, failures); connectors table, `odbc`, `file`, `rest`; "Types" (Files).
- `docs/decisions.md`: decisions 44, 45, 46; decision 41, price (also not as a match of a pattern).
- `docs/open-points.md`: removed `run` before `key new` and JSON files; added the limits of tickets 02 and 03.
- `CHANGELOG.md`: `Unreleased` with Added, Changed (the two CSV changes, not confirmed by the owner), Fixed.
- `examples/quickstart/compose.yaml`: `rowvioli key new && rowvioli apply --init && rowvioli run`; run once, both tables ok, status and rows shown, then `down -v --rmi local`.

Not as the tickets said: decision 14 is the Git checkout, not "apply does not know the connectors"; that rule is in decision 22 (and open points), so decision 45 cites 22. Ticket 01 says the first-mirror steps were changed in the README; there is no such section, the start at the top and "Commands" carry it. `type = "test"` fails with `did you mean rest?` (as the ticket expects, one letter from `rest`). Not tried: `.xlsx`, Windows, odbc without libodbc (taken from ticket 01), `result.items` nesting (taken from ticket 02; `rows = "data"` and a missing field were run).

