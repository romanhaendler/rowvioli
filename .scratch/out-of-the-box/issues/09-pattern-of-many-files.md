# 09: A pattern reads any number of files

**Blocked by:** none

**Status:** ready-for-agent

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
