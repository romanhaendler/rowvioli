# 02: The log says when the target is reachable again

**Status:** resolved

**Model:** Sonnet

From `.scratch/shakedown/fifth-run.md` (H4).

## What to build

`work` writes `⚠ the target is unreachable, …` once per outage and nothing when it ends, so a log does not show how long the outage lasted.

- When the worker has its connection back, one line: `✔ the target is reachable again after <seconds>s`.
- Once per outage, like the `⚠` line. `run` has no such line: it fails on an unreachable target.
- `docs/operation.md` and the example there name the line.

## Acceptance criteria

- [ ] The existing test for the unreachable target (or one next to it) restarts the target and sees the `⚠` line once and then the new line once.

## Comments

`loop` remembers when the target became unreachable and writes the `✔` line once when its next query succeeds; the restart test asserts both lines once.
