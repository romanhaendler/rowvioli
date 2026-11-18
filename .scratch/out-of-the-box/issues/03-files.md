# 03: Files: JSON, a pattern, the CSV leads

**Blocked by:** none

**Status:** resolved

**Model:** Opus

Spec: `.scratch/out-of-the-box/spec.md` (read it first, also "Testing Decisions"). Behaviour reference: `README.md`, `docs/decisions.md`. Tests: `tests/conftest.py`, `rv` fixture. Documents are ticket 04: change no `.md` outside your ticket file, but list under `## Comments` every sentence the documents need.

## What to build

In `src/rowvioli/connectors/file.py` (and `definition.py` for the one `apply` check):

- **JSON**: `.json`, `.jsonl`, `.ndjson` through DuckDB's reader. Find out and measure what arrives in the
  target for numbers, dates, nulls, nested objects and arrays, and for a second run (the diff needs equality).
  A value that cannot arrive right fails the run and names the column. `tables` lists these files too.
- **A pattern**: a table name with `*` or `?` reads every matching file as one table. The connector expands
  it inside the connection's `path`, resolves every match and refuses any outside (symlink, `..`, absolute);
  no match fails. Files of different extensions or columns fail with a reason a person can act on. `apply`
  fails for a pattern without `target_table` and says so.
- **Leads from the second shakedown**, reproduce first: a CSV with an unterminated quote loads two rows
  without an error (a silent wrong); a ragged CSV names the wrong cause (`has no column id; it has: id,name`).
  Fix what goes red and can be fixed in the connector; record the rest in the comment as a known limit.

## Acceptance criteria

- [ ] A JSON and a JSON-lines file mirror, and a second unchanged run reports no change.
- [ ] `orders_*.csv` over two files mirrors both; a third file arrives on the next run.
- [ ] A pattern cannot read outside `path`: the existing confinement tests have a pattern twin.
- [ ] The whole suite is green.

## Comments

2026-11-17, Opus. All in `connectors/file.py`, one check in `definition.py`; tests in `tests/test_file.py`, and
`tests/test_list.py` now lists a `.jsonl` file (its `orders.csv` got a second column, see "Price").

### What was built

- **JSON arrives as jsonb, one column per top-level key, every value as written.** DuckDB's `read_json` is called
  with `maximum_depth = 1` and `records = true` (both fixed, like `all_varchar` for CSV) and `sample_size = -1`
  (a default the table may lower). The connector marks DuckDB's JSON columns as Arrow's `json`, which the staging
  step already turns into `jsonb`. `columns` casts a JSON value from its text (`->>'$'`), so `"Anna"` as `text` loses
  its quotes, as in a CSV.
  Why not DuckDB's own types: they are guessed from the first 20480 rows, which README "Arrow only" rules out
  (types could flip between two runs), and nested objects become Arrow structs, which the driver refuses
  (`Can't map Arrow type 'struct'`). Why not `arrow_lossless_conversion`: it does mark JSON, but it also turned a
  `columns` `hugeint` into `bytea` and a `boolean` into `smallint` (measured), silently.
- **A pattern** (`*` or `?` in the table name) is expanded by the connector with `glob.glob(table, root_dir=path)`.
  Every match is resolved and checked as a single file is: inside `path` (also through a symlink, a symlinked
  directory, `..`, an absolute pattern), a known extension, a file. No match fails (`no file in … matches`), so do
  matches of different kinds (`matches .csv and .json files; a table reads files of one kind`) and a file whose
  columns or types differ from the first's (`orders_3.csv has the columns order_no VARCHAR, …, orders_1.csv has …`).
  Files are joined in sorted order. `apply` fails for a pattern without `target_table`.
- **Not a list to DuckDB, as the spec said, but one DuckDB relation per file, joined by name** (`union` after
  projecting each onto the first file's columns). Reason: `read_xlsx` takes no list, and the per-file relations are
  needed anyway to compare the columns, so this costs no extra read. A list to `read_csv` would also have dropped a
  column the first file lacks, silently (measured).
- **Every path handed to DuckDB is escaped with `glob.escape`.** DuckDB expands `*`, `?` and `[` in any path it is
  given, also a single file: before, the table `x[1].csv` read `x1.csv`, and `q?.csv` read `q?.csv` and every sibling
  such as `qz.csv`, which could be a symlink out of `path` that nobody checked (measured; new test). DuckDB accepts
  `[[]` for a literal `[`, which is what `glob.escape` writes. Not tried on Windows.
- **CSV: `skip = 0` by default, and a CSV that splits into one column fails unless `sep` is given**, with
  `no separator splits every line into the same number of fields; fix the lines, or set sep (also for a file of one
  column) and skip (for lines before the header)`.

### The leads

- **Ragged CSV: red, fixed.** Two silent wrongs, depending on the file: `id,name\n1,Anna\n2,Ben,extra\n3,Cleo\n`
  became one column `id,name` (with a key: `has no column id; it has: id,name`, without one: a mirror of one column);
  `id,name\n1,Anna\n2,Ben,extra\n` became columns `column0..2` holding only the last line, the header and the first
  row dropped as "lines before the header". With `skip = 0` both become one column, and the check fails them.
- **Unterminated quote: red, not fixed.** `id,name\n1,"Anna\n2,Ben\n` loads two rows, the first with the value
  `"Anna`: DuckDB's sniffer chooses no quote character when `"` does not parse. Forcing `quote = '"'` would make it
  fail, but would also fail files with a literal `"` in an unquoted field (`1,5" pipe`), which load right today.
  With `quote = '"'` set by the author such a file fails (measured, with the message above). Known limit.

### What was measured (DuckDB 2.0.0, pyarrow 26.0.1, ADBC 1.13.0, Postgres 16)

| In the file | In the target (jsonb) |
|---|---|
| `1`, `2.5`, `true`, `"x"` | `1`, `2.5`, `true`, `"x"` |
| `12345678901234567890`, `123456789012345678901234567890`, `1e400` | the same number, exactly |
| `0.12345678901234567890123` | `0.12345678901234568`: a number with a fraction passes through a double |
| `"2024-01-02"`, `"2024-01-02T03:04:05+02:00"` | the strings, not guessed as dates |
| `null`, a missing key | SQL `NULL` (not jsonb `null`) |
| `{"a": 1, "b": [1, 2]}`, `[[1, 2], [3, 4]]`, `[{"x": 1}, {"y": "z"}]` | as written; no keys added, nothing flattened |
| `1` in one row, `"two"` in another | `1` and `"two"` |
| 25000 lines, a key and a string first after line 25000 | arrives (with DuckDB's default sample it failed: `has unknown key`) |
| a second unchanged run, `.json` and `.jsonl` | `inserted 0, updated 0, deleted 0` |
| `[]`, an empty `.jsonl`, `[1, 2]` | fails: `json_read expected records, but got non-record JSON instead.` |
| an object with a key twice; a cut-off file | fails, naming the key; fails, naming the byte |

With `columns`: `bigint`, `date`, `decimal(10,2)`, `hugeint` (as `numeric`), `boolean`, `timestamptz` (the offset
applied) and `text` arrive right; an object cast to `text` is its JSON text.

### Price

- **Two working set-ups change, loudly:** a CSV of a single column now needs `sep`, and a CSV with lines before
  its header needs `skip` (DuckDB used to drop them by itself, by the same rule that dropped the ragged file's
  header). Both fail with the message above, which names the option. The spec's "whoever has a working set-up sees
  no change" does not hold for these two; I chose a loud failure over the silent ones.
- A pattern of JSON files reads each file twice (once for its columns with `sample_size = -1`, once for the rows);
  a single JSON file too.

### New known limits

- A JSON number with a fraction passes through a 64-bit float: beyond 15 to 17 significant digits it is rounded,
  as in most JSON readers. Whole numbers of any size and exponents arrive exactly.
- A JSON file holds objects: an empty file and one of other values fail with DuckDB's words above, which do not say
  "empty". A file that is one object (`{"data": [...]}`) is one row.
- Across the files of a pattern a column must be in every file: a JSON key that one file lacks fails the run,
  while inside a file it is null.
- `*` does not match a name starting with a dot, and `**` is one directory level, like `*`.
- `columns` casts as DuckDB does, for CSV as before and now for JSON: `1.7` as `integer` becomes `2`. Found, not
  changed (it is not this ticket's; worth its own).
- DuckDB's messages can name a value of the file (the record with an unknown key, a value that does not cast), as
  CSV casts did before.

### Sentences for the documents (ticket 04)

README, "file" section, replacing its first sentence and the "options" sentence:

> **`file`** reads one file per table from the directory `path` of the connection, by extension: `.csv`, `.xlsx`,
> `.parquet`, and `.json`, `.jsonl` or `.ndjson` for JSON. A table is the file name as written in the definition,
> or a pattern with `*` or `?` such as `orders_*.csv`, which reads every matching file as one table; a file that
> lands later arrives on the next run. A pattern needs `target_table`, and its files must be of one kind and have
> the same columns, or the run fails and names the file. Every file, also each match of a pattern, must lie inside
> `path`: a name or a match that leaves it (`../x.csv`, an absolute path, a symbolic link) fails the run and names
> the table.

> A JSON file holds objects, as an array or one per line. Each key becomes a column of type `jsonb` holding the
> value as written, nested objects and arrays too, so a type never changes between two runs; `columns` gives a
> column a DuckDB type, cast from the value's text (`columns = { id = "bigint", name = "text" }`). A number with a
> fraction passes through a 64-bit float, so beyond 15 to 17 significant digits it is rounded. An empty JSON file
> fails, since it names no column.

> A CSV skips no line before its header unless `skip` says so. A CSV that splits into a single column fails unless
> `sep` is given, because that is how DuckDB reads a file whose lines have different numbers of fields; a file of
> one column needs `sep = ","`. A field with a quote that is never closed is read as text with the quote in it;
> `quote = '"'` makes such a file fail.

> An option the reader does not know fails the run. The options are those of DuckDB's `read_csv`, `read_xlsx`,
> `read_parquet` and `read_json`; for JSON, `maximum_depth` and `records` are fixed.

README line "Version 0.1.0 ships `postgres`, `file` (without JSON)…" and the connector table (`CSV, Excel, Parquet`):
add JSON and patterns. README "Files." limit (line ~990): "…every CSV and Excel column as text and every JSON
column as `jsonb`, except those the option `columns` names…". Decision 41, Price: "…cannot read through a symbolic
link that leaves its directory, also not as a match of a pattern." `docs/open-points.md`: drop "JSON files in the
`file` connector" from "Not built"; "patterns for table names" there means source tables and stays. Changelog:
"The `file` connector reads JSON files (as `jsonb`) and patterns such as `orders_*.csv`. A ragged CSV fails instead
of losing its header or arriving as one column; a CSV of one column needs `sep`, one with lines before its header
needs `skip`. A file name with `[`, `*` or `?` is no longer expanded a second time by DuckDB."
