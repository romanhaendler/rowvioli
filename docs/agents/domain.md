# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/decisions.md`**: every decision of the concept in one file, numbered. Read the ones that touch the area you are about to work in. A decision marked "Replaced by", "Changed by" or "Dropped by decision N" no longer holds as written.

This repo has no `docs/adr/`. A new decision is appended to `docs/decisions.md` under the next number, not written as a separate ADR file.

## File structure

Single-context repo:

```
/
├── GLOSSARY.md
├── docs/decisions.md
└── src/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag conflicts with decisions

If your output contradicts an existing decision, surface it explicitly rather than silently overriding:

> _Contradicts decision 21 (tables are named in the definition), but worth reopening because…_
