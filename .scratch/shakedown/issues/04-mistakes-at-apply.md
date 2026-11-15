# 04: Mistakes named at apply, init and key new

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/shakedown/spec.md`. Findings and repros: `.scratch/shakedown/*.md`. Tests: the existing seam (`tests/conftest.py`, `rv` fixture), real processes against PostgreSQL in Docker, no import of the program. Spec "Testing Decisions" apply; each finding's repro is the first red test. Unconfirmed findings (no ✓) are reproduced first and dropped if they do not go red.

## What to build

Spec stories 20–26, 33, 34 and the decisions on settings typos, the empty directory, the default public key, `init`/`key new` output and the reserved-name message.

- A key one or two edits from a rowvioli setting (source and table level) fails `apply`/`apply --check` with "did you mean `<setting>`"; other unknown keys pass to the connector as today.
- A directory without source files fails, naming it and saying it would disable every table.
- Default public key: `worker.pub` in the parent of the directory given to `apply`; when missing, the message names the path tried. `--key` keeps working and gets a test.
- `init` and `key new` print one line saying what they created.
- Reserved-name message: `log = false` frees `_run`, `_loaded_at`, `_valid_from`, `_valid_to`; `_op` cannot be freed.

## Acceptance criteria

- [ ] `max_agee`, `logg`, `timzone`, `targt_table` each fail with the right suggestion; a far-off option reaches the connector.
- [ ] `apply` of an empty directory exits non-zero and disables nothing.
- [ ] `apply sources/` from the parent finds `worker.pub` there.

## Comments
