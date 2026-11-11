# `apply`: definition, placeholders, sealed connections

Status: ready-for-agent
Blocked by: 01

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

Spec sections "Definition", "apply", "Connections" (sealing and opening, source name bound into the box). User stories 3-14, 42.

## Acceptance criteria

- [ ] Spec tests 1, 2, 3 pass.
- [ ] Spec test 4 as far as `apply` goes: a removed table is disabled, nothing is deleted.
- [ ] Spec test 20: a shortened maximum age changes `due_at` in `status` without a run.
- [ ] The stored connection does not contain the password (first part of spec test 18).
- [ ] `apply` needs no source database and no driver for it (user story 10).
