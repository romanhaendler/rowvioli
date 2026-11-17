# 09: A pattern reads any number of files

**Blocked by:** none

**Status:** resolved

**Model:** Opus

From the review of 2026-11-18 (findings 1 and 8), confirmed there by running.

## What to build

- **A pattern over more than 333 files fails every run** (`Binder Error: Max expression depth limit of 1000
  exceeded`), and every matched file holds a file handle until the read ends (`Too many open files` with
  `ulimit -n 200` and 320 files). A file that lands daily stops loading after eleven months. The review's
  fix, tried there with 1000 files and 4 file descriptors: keep the per-file column check but release each
  relation after reading its columns, then read once with the list of escaped paths (csv, json, parquet);
  xlsx, whose reader takes no list, keeps the union. The earlier measurement stands: a list given to
  `read_csv` drops a column the first file lacks, so the per-file check stays in front of it.
- **An empty CSV fails with the wrong cause** (`no separator splits every line...`). It says that the file is empty.
- What stays limited (xlsx patterns) goes into the comment as a known limit with its number.

## Acceptance criteria

- [ ] 1000 daily CSV files mirror as one table; the same for JSON lines; the open file handles stay small.
- [ ] Rows that are equal in two files are both kept; files with columns in another order load right.
- [ ] Every confinement and escaping test of ticket 03 still passes.
- [ ] `tests/test_file.py` and `tests/test_list.py` are green.

## Comments

2026-11-17, Opus. Only `connectors/file.py` and `tests/test_file.py` changed.

### What was built

- **The column check stays in front of every read and holds no file.** Each file's relation is bound, its columns
  and types are taken, and it is dropped; a file whose columns or types differ from the first's fails as before.
- **A pattern is read 50 files at a time (`FILES_PER_READ`), one read after the other**, each a list of the
  resolved, checked and escaped paths for csv, json and parquet, and a union of the 50 for xlsx. Each read is
  projected onto the first file's columns by name, then the casts of `columns`; the batches of all reads go out as
  one stream. A single file is a list of one.
- **The review's fix (one read over the whole list) was not enough here**, measured on macOS, 8 cores, DuckDB 2.0.0:
  a list read of tiny CSV files held 130 files open at 250 files, about 360 to 450 at 1000 to 2000, 622 once at
  5000 (`threads = 1`: about 127; `max_streaming_buffer_size` changed nothing reliable). With `ulimit -n 128` it
  failed at `day_0145.csv`: `Too many open files`. JSON lines held 12. And with `union_by_name = true`, 1000 JSON
  lines files ran out of memory (`failed to allocate data of size 32.0 MiB (12.7 GiB/12.7 GiB used)`), so it is not
  used: a list read maps columns by name without it (the test with `b,a` after `a,b` shows it), and the check
  before it makes the columns equal.
- **With groups of 50**, through the connector: 5000 tiny CSV files 55 files open at most, 2.7 s, 142 MB RSS;
  1000 CSV files of 3000 rows (3 million rows) 55, 3.3 s, 142 MB; 1000 JSON lines files 12, 0.3 s, 92 MB; 1000 xlsx
  files 54, 4.1 s, 122 MB. Most of the time is the check, about 3 ms per file.
- **An empty file fails with `<name>: the file is empty`** (any kind, by its size), not with the separator message.
- Tests: 1000 daily CSV files and 1000 JSON lines files as one table, each run under `ulimit -n 128` (the run's
  process inherits it; `sh -c 'ulimit -n 128 && exec rowvioli run'`). Red before: `Binder Error: Max expression
  depth limit of 1000 exceeded` for both. With `FILES_PER_READ = 1000` the CSV one fails with `Too many open
  files`, so it guards the handles; the JSON one guards the depth and the memory. Equal rows in two files are both
  kept and a file with its columns in another order loads right (one test). The empty CSV has its test. Every
  confinement and escaping test of ticket 03 passes unchanged.

### Known limit

- xlsx: no limit of files any more (the union is of 50, under DuckDB's depth of 1000; 1000 files measured).
  What stays: each file's columns are checked one by one, about 3 ms per file, so 10000 files take half a minute
  before the first row.
- 50 is a guess that keeps the files open at 55 with a process limit of 128 and costs nothing measurable; the
  open files of one read were not measured on Linux.

### Sentence for the documents (ticket 04)

> A pattern reads any number of files, 50 at a time, so a file that lands daily keeps loading; each file's
> columns are checked first, a few milliseconds per file. An empty file fails and says so.
