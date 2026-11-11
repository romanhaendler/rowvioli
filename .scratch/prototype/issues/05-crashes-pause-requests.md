# Killed runs, pause, requests, readers

Status: ready-for-agent
Blocked by: 03

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

Whatever is missing so that the guarantees hold under real crashes; mostly tests. User stories 25, 26, 30, 32-35. Hold a run at each step from the SQL side as "Testing Decisions" describes; if that turns out impossible, note it in a comment on this ticket (question 6 of the spec).

## Acceptance criteria

- [ ] Spec tests 9, 10, 11, 12 pass.
- [ ] Spec test 22: `loading` is visible only while the table lock is held.
