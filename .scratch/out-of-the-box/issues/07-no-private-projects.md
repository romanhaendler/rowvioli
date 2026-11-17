# 07: No reference to a project that exists only on the owner's machine

**Blocked by:** none

**Status:** resolved

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

**Places changed**

- `docs/decisions.md`: the sentence in the preamble naming the earlier projects (now "Evidence refers to `docs/measurements.md`."); the paragraph "Three earlier attempts exist ..." and "new attempt" in the Starting point (now "The first idea was ..."); decision 1 Why ("All earlier projects loaded into Postgres.") and Price (the `data-extractor` note); decision 2 Price (now restated on rowvioli's own measurement: staging, diff and publishing add up to more than a minute at 10^7 rows) and the "(as in ...)" in Rejected; decision 3 Rejected (the ADR sentence); decision 6 (the `data-extractor` agreement and COPY comparison); decision 7 (the fencing token sentence); decision 9 Why (`hpdl` layered settings); decision 12 Why (the `hpdl` bottleneck bullet); decision 16 Why (the ADR-0012 sentence); decision 18 Why (the `dataly` sentence).
- `docs/measurements.md`: "shaped after the `lineitem` table of the `hpdl` benchmark" in the Set-up; the `data-extractor` sentence in section 4; the `data-extractor` sentence in section 6; the whole section "Reference: hpdl" (it had no row in the summary table and nothing linked to it).
- `docs/open-points.md`: "`data-extractor` has experience with ODBC."; the known limit now reads "At 10^7 rows a run takes over a minute", with its own numbers unchanged.
- `README.md`: "This was investigated in `data-extractor` (ADR-0014 there)." in the section Types.
- `docs/agents/shakedown/README.md`: "Taken over from the project umriss, cut down to ..." (now "It covers what fits a program that mirrors tables: ...").
- `docs/agents/shakedown/personas.md`: "Ids follow umriss ..."; "(or `~/cc/hpdl`)" in P16.
- `.scratch/visibility/spec.md` and `.scratch/target-names-and-history/spec.md`: `../rowvioli-demo`, a directory outside the repo (the quote in the first stays, the second loses its bullet).

**Deleted claims that had no other evidence**

- Azure Database for PostgreSQL has all the coordination mechanisms (session locks, transactions, `pg_locks`), Fabric and Databricks do not (decision 1).
- Compare-by-hash is faster for large tables is still stated in Rejected; but "the bottleneck was never the worker but source and target" (decision 12, measurements "Reference: hpdl") is gone, as are the hpdl timings at 10^6 and 10^7 rows.
- A competing design reached the same conclusion on TEMP staging and measured COPY into a TEMP table equal to an unlogged one at 10^6 rows through ADBC (0.42 s against 0.46 s) (decision 6, measurements section 6). Rowvioli's own 16.4 s against 10.6 s stays, "not investigated".
- Swapping tables took several ADRs elsewhere (decision 3); a fencing token was needed there (decision 7); vendor ODBC drivers in an image were decided the same way (decision 16); another project has the same zero-rows rule (decision 18); layered settings existed for the same reason as one file per source (decision 9).
- Measurements section 4: a TCP-keepalive failure of about 60 s was expected elsewhere. Rowvioli's own measurement (62 s) is in `docs/open-points.md` and stays.
- "Experience with ODBC" (open points).
