# 13: Three things the pages do not say

**Status:** ready-for-agent

**Model:** Sonnet

From `.scratch/shakedown/sixth-run.md` (P3, P20).

- `docs/loading.md`, "What a person does by hand": a column dropped in the source fails the table with `column x is missing in the source` for good. The recipe a host found and checked: drop the history view, drop the column from the mirror and from `<table>__log`, run again; the view comes back and the log still replays to the mirror. Verify the recipe once against a throwaway target before writing it down, statement by statement.
- `docs/target.md`: a consumer who may read only the mirrors cannot tell a mirror that stopped (a failed run) from a quiet source; only `_rowvioli.status` shows it, and `docs/operation.md` calls that grant optional. Say it where the consumer reads, with the two grant statements.
- `docs/target.md`: a consumer's own `SELECT *` view over a mirror keeps its columns when the source gains one (Postgres fixes a view's columns when it is created).
