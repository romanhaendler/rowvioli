# `run`: one table from source to mirror

Status: ready-for-agent
Blocked by: 02

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

The thin end-to-end slice: worker loop (one function, later shared with `work`), a fresh process per run, claim on the control connection, opening the sealed connection, connector registry with `postgres`, TEMP staging, diff, publishing with mirror creation and change log, the JSON answer and exit code of `run`, `run <source>` and `run <source> <table>`. Spec sections "Worker loop and claim", "One run", "Connector", "Answer of run". Only what a successful run needs; checks and failure paths belong to tickets 04-06, but a failing run must already record `failed` with a reason and exit code 1.

## Acceptance criteria

- [ ] Spec tests 5, 6, 7, 8, 21 pass.
- [ ] Rest of spec test 4: a disabled table is not loaded again, its mirror stays.
- [ ] `status` shows `ok` after a run; `runs` has one row per run with worker, start, end, status, counts.
