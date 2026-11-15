# Shakedown 2026-11-15: source data

Status: needs-triage (taken up in `spec.md`)

From H2 (50 source tables, a file and a REST source, compared by md5 of the row text). Not covered: other
Postgres versions, ODBC, more than 300 columns.

## Findings

1. ✓ **[Break] `json` and `jsonb` columns load once and fail on every later run** with `operator does not
   exist: json = json` and raw SQL in the reason. `jsonb` arrives as `json`. The table stays at its first
   state. documented: open points says json has to arrive as jsonb or text, but the first run succeeds.
   Idea: map both to `jsonb` in the connector, or fail on the first run.
2. ✓ **[Wrong] Types the driver cannot name arrive as raw binary in `bytea`, the run is `ok`.** inet
   `10.0.0.1/8` → `\x020800040a000001`, xml, `timetz`, `bit`, `point`, ranges, `tsvector` the same; `money`
   `$12.50` → bigint `1250`. documented: partly ("the driver decides the types"). Idea: fail on a column that
   becomes `bytea` from another source type, or cast to text in the connector.
3. **[Wrong] A multi-dimensional array is flattened silently:** `{{1,2},{3,4}}` → `{1,2,3,4}`.
4. **[Wrong] A renamed REST field empties its column, the run is `ok`** (`updated: 9`, `count(name)` = 0).
   documented: "a missing field is null". Idea: fail when a named column is absent from every row of a page.
5. **[Wrong] An empty REST page in the middle ends paging**: 6 of 9 rows published, under the 50 % delete limit.
6. **[Break] Messages that name no cause or the wrong one:** `timestamptz 'infinity'` → `IO: Error occurred
   writing COPY data: ` and nothing more; numeric beyond 38 digits or `NaN` → a pyarrow traceback with absolute
   paths in the reason, no column named; a ragged CSV → `column "id" does not exist ... _stage`; a late REST
   page failure wrapped in `nanoarrow call failed ... Traceback`. Idea: strip the driver wrapper, name table and column.
7. **[Misfit] An empty source table can never be mirrored** (`the source delivered zero rows`). documented:
   safety limits; an opt-in per table is missing.
8. **[Misfit] REST requests time out after a fixed 5 s, and a frozen source holds its run until `max_seconds`**
   (an hour by default; no connect timeout).
9. **[Wrong, minor]** A quoted empty CSV cell becomes NULL; a duplicate CSV header becomes `id_1` silently;
   the message for `_op` with `log = false` suggests no way out although `log = false` is the way out for the
   other reserved names.

## What held up

- Every failed first load left nothing behind; every failed later load kept the old mirror.
- Type change, dropped key column, dropped column, dropped table: each failed with the old state intact, and the README's recipe rebuilt it.
- Identifiers with capitals, spaces, quotes, umlauts and keywords; 300 columns; composite and text keys; NaN/infinity/-0 floats; timestamps from year 1 and +14 h; bytea, plain arrays, uuid; text with control bytes and emoji.
- File: BOM, `;`, quoted newlines, umlauts, added columns, `.CSV`, a space in the name. REST: 500s, HTML, wrapped objects failed with the old mirror kept; a 67 % truncation was caught.
