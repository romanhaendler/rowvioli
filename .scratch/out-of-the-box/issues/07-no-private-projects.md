# 07: No reference to a project that exists only on the owner's machine

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

The repo is public. It refers to projects a reader cannot see: `hpdl`, `data-extractor`, `dataly`, `umriss`
(also their ADR numbers, file paths such as `hpdl/docs/performance.md`, `docs/notiz-weitere-ziele.md`,
`~/cc/hpdl`, and "in the same workspace"). They go, completely.

## What to build

- Find every such reference in the whole repo, `.scratch/` and `docs/agents/` included. Known: `docs/decisions.md`,
  `docs/measurements.md` (also the section "Reference: hpdl" and its row in the summary), `docs/open-points.md`,
  `docs/agents/shakedown/README.md` and `personas.md`. Look for others: any project name, path outside the
  repo, or "earlier project/attempt" that points at something not public.
- The rule for each place:
  - A sentence that only cites the other project as evidence, history or comparison is deleted.
  - A sentence that carries a reason which stands by itself keeps the reason and loses the reference.
  - No paraphrase in its place ("an earlier project", "a previous attempt"): the reader cannot check that either.
  - A claim that then rests on nothing is deleted, or restated on rowvioli's own measurement if
    `docs/measurements.md` has one (the known limit at 10⁷ rows keeps its own numbers: staging, diff and
    publishing add up to more than a minute).
- Text reads as if the reference had never been there: no dangling "as above", no empty section, no broken
  anchor or table of contents entry, numbering intact.
- Not a private project, so they stay: `rowvioli` itself and its GitHub URLs, public tools (Sling, ingestr, dlt,
  Airbyte, DuckDB, PgBouncer), `dwh` and `hr` as example database names, `rowvioli-demo` only if it is a
  container or compose name in this repo (check; remove if it points at a directory outside it).

## Acceptance criteria

- [ ] `git grep -I -i -E "hpdl|data-extractor|dataly|umriss|ADR-[0-9]|same workspace|~/cc"` finds nothing.
- [ ] Every link and anchor in the changed files still resolves; `uv run pytest tests/test_guide.py tests/test_licences.py` passes.
- [ ] The comment lists every deleted claim that had no other evidence, so the owner can see what the documents no longer say.

## Comments
