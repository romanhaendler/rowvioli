## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the root, decisions in `docs/decisions.md`. See `docs/agents/domain.md`.

### Shakedown

Before a release: the built wheel in hostile set-ups and in the hands of personas. See `docs/agents/shakedown/README.md`.

## Choosing the model

Before implementing anything, decide which model the work needs, and take the smallest that fits.

- **Sonnet and Opus are the standard**, chosen by the weight of the task: Sonnet for work that is specified and mechanical, Opus for work that needs judgement.
- **Fable should practically never be needed.** If a task seems to need it, it is too large or unclear: cut or clarify it first.
- **Opus does the review at the end.**

A session running on a larger model delegates the implementation to an agent on the chosen model instead of doing it itself. Specs and tickets carry the estimate (see "Who implements" in `.scratch/visibility/spec.md`).
