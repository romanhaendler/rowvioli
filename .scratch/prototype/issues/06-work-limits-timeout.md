# `work`, order, limits, `max_seconds`

Status: ready-for-agent
Blocked by: 03

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

The `work` command (`--slots`, target address, `ROWVIOLI_KEY_FILE`), most-overdue-first, both limits through the one counting lock, ending a run after `max_seconds`. User stories 15, 16, 21-24.

## Acceptance criteria

- [ ] Spec tests 13, 14, 19 pass.
