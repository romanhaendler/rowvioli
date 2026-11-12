# Findings for the owner

Status: resolved
Blocked by: 04, 05, 06

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

`.scratch/prototype/findings.md`: an answer, with what was observed (measure where the question asks for a cost), to each of the seven questions under "Further Notes" in the spec, and a list of every point where the prototype had to deviate from `README.md`, `GLOSSARY.md` or `docs/decisions.md`, naming for each whether the documents hold and what has to change. Read the comments on tickets 01-06 and the code. Do not edit the documents themselves (out of scope).

## Acceptance criteria

- [ ] All seven questions answered from observation, not from reading the docs.
- [ ] Full test suite passes; any spec test that is missing or skipped is listed with the reason.
