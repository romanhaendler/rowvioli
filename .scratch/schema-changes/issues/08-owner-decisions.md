# 08: What the owner decided during the build

**Blocked by:** 06

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/schema-changes/spec.md`. Decided by the owner on 2026-11-24, after the reviews of tickets 03 to 05 (see their comments).

## What to build

1. **A file or REST table without a change log stops again when a mirror column is missing from the data**, with today's reason and its way out, instead of filling the column with nothing on every run. With a change log nothing changes (the change log says whether the column is the source's). This leaves the spec's decision 3 for this one case, because a person's own column would be emptied in silence (story 8).
2. **`rowvioli init`, when it brings a target from version 3 to 4, prints the `GRANT` statements a worker's role needs for the new objects** (`_rowvioli.columns`, `_rowvioli.columns__log`), as text; the program still grants nothing. The same statements go into `docs/operation.md` and the changelog (ticket 07).
3. **Every shipped connector says its driver's version** (`driver_version`, the optional contract entry from ticket 01), so that `by = reader` sees a changed driver (story 38).

## Acceptance criteria

- [ ] A test for each of the three, at the existing seam.
- [ ] The existing tests pass or are changed to the new behaviour.

## Comments
