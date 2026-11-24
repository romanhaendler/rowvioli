# 08: What the owner decided during the build

**Blocked by:** 06

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/schema-changes/spec.md`. Decided by the owner on 2026-11-24, after the reviews of tickets 03 to 05 (see their comments).

## What to build

1. **A file or REST table without a change log stops again when a mirror column is missing from the data**, with today's reason and its way out, instead of filling the column with nothing on every run. With a change log nothing changes (the change log says whether the column is the source's). This leaves the spec's decision 3 for this one case, because a person's own column would be emptied in silence (story 8).
2. **`rowvioli init`, when it brings a target from version 3 to 4, prints the `GRANT` statements a worker's role needs for the new objects** (`_rowvioli.columns`, `_rowvioli.columns__log`), as text; the program still grants nothing. The same statements go into `docs/operation.md` and the changelog (ticket 07).
3. **Every shipped connector says its driver's version** (`driver_version`, the optional contract entry from ticket 01), so that `by = reader` sees a changed driver (story 38).
4. **Where the definition names the columns, the definition is the catalog.** This replaces the stop of spec decision 6 for a type named under `columns` (file and REST), and `cases.md` B11 holds: "by the same rules".
   - A type under `columns` changed to another family (also a first type given to a CSV column that was loaded as `text`): with a change log the column goes and comes in one run, the old values stay under `<name>__<run>`, recorded with `by = definition`. In the same family: fit and widening as for any column.
   - A column taken out of a REST table's `columns`: it leaves the mirror and stays in the change log, as a column a database source dropped, `by = definition`.
   - Unchanged: a field named in `columns` and missing from the data is empty and never goes; a type the file itself brings (Parquet) in another family still stops with the hint to pin it under `columns`; without a change log everything here stops as today, with the way out.
5. **A type changed by hand in the mirror to another family (`cases.md` G4) keeps stopping, and the reason says the way out** (story 47). Find by test which way out works (the type put back, or the column dropped from the mirror so the next run brings it) and name that one.

## Acceptance criteria

- [ ] A test for each of the five, at the existing seam; the replay invariant where columns change.
- [ ] The existing tests pass or are changed to the new behaviour.

## Comments
