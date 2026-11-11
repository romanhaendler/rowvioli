# Checks, failure reasons, no secret leaks

Status: ready-for-agent
Blocked by: 03

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

Spec "One run" checks, unknown connector type, wrong private key, ciphertext swapped between sources, scrubbing connection values from every reason, `runs` row and output. User stories 27, 28, 38-40, 43, 44.

## Acceptance criteria

- [ ] Spec tests 15, 16, 17, 18 pass.
