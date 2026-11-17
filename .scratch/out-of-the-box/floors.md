# Dependency floors

Question: how low can each floor honestly go? A floor is lowered only to a version on which the whole suite passed
(`pytest -q`, 4 workers, `tests/conftest.py` finds `rowvioli` beside the interpreter, so each run used its own
virtual environment). One dependency at a time with the rest at the locked versions, then all floors together.
Stop rule: about two years old (today is 2026-11-17) or the first failure.

Environment: macOS arm64, Python 3.11.8 (the package's floor) and 3.13.12 (newest of the CI matrix 3.11/3.12/3.13).
Locked: pyarrow 26.0.1, adbc-driver-postgresql 1.13.0, pynacl 1.6.2, duckdb 2.0.0, arrow-odbc 10.7.0, httpx 0.28.1.
Every run printed its versions first (`uv pip list`) and kept them with the result.

Baseline, locked versions, 3.11: `389 passed, 7 skipped in 219.34s`. The 7 skipped are the odbc tests: macOS has no
psqlODBC. So the odbc connector was tested separately on Linux (below).

## Decision

| Dependency | Old | New | Why not lower |
|---|---|---|---|
| `pyarrow` | >=26 | **>=19** | 18.1.0: `module 'pyarrow' has no attribute 'json_'` (5 tests, JSON columns) |
| `adbc-driver-postgresql` | >=1.13 | >=1.13 (unchanged) | 1.12.0 still fails 4 numeric/uuid tests |
| `pynacl` | >=1.6 | **>=1.5** | 1.5.0 is the release before 1.6 (2022); not tried lower: older than two years |
| `duckdb` | >=2 | **>=1.5** | 1.4.5 (and 1.4.4, 1.4.0, 1.3, 1.2): no `to_arrow_reader` on the result; 1.1.3: no `xlsx` copy function |
| `arrow-odbc` | >=10.7 | **>=9.3.0** | 9.2.0: `'module' object is not callable` (`arrow_odbc.connect`); 8.x also has no Linux arm64 wheel |
| `httpx` | >=0.28 | >=0.28 (unchanged) | 0.28.0 passed; there is nothing older within two years |

All floors together: 3.11 `389 passed, 7 skipped in 153.96s`, 3.13 `389 passed, 7 skipped in 146.06s`
(pyarrow 19.0.0, adbc 1.13.0, pynacl 1.5.0, duckdb 1.5.0, arrow-odbc 9.3.0, httpx 0.28.0).
odbc on Linux arm64 (container with unixODBC and psqlODBC, `tests/test_odbc.py`) on the same floors:
3.11 `7 passed, 1 skipped in 15.43s`, 3.13 `7 passed, 1 skipped in 17.08s`.

CI: the `tests` job has two more entries (3.11 and 3.13, `lowest: true`) that run
`uv pip install --upgrade --resolution lowest-direct -e ".[file,odbc,rest]"` after the locked sync, then
`uv run --no-sync pytest`. Checked locally that it installs exactly the floors above and leaves pytest and psycopg at
their locked versions (`--upgrade` is needed: without it uv keeps the installed higher versions; `--no-sync` is needed:
`uv run` would put the locked versions back). Transitive packages (adbc-driver-manager 1.13.0, cffi, ...) stay locked.

## pyarrow (others locked), 3.11

| Version | Result |
|---|---|
| 26.0.1 (locked) | 389 passed, 7 skipped |
| 19.0.0 | 389 passed, 7 skipped in 165.59s |
| 18.1.0 | 5 failed, 384 passed, 7 skipped in 257.00s (`module 'pyarrow' has no attribute 'json_'`) |

Stopped at the first failure; 18.1.0 is also the two-year mark (2024-11).

## adbc-driver-postgresql (others locked), 3.11

adbc-driver-manager stayed at 1.13.0 in these runs.

| Version | Result |
|---|---|
| 1.13.0 (locked) | 389 passed, 7 skipped |
| 1.12.0 | 4 failed, 385 passed, 7 skipped in 172.19s (numeric and uuid arrive as text: `('u', 'text') != ('u', 'uuid')`) |
| 1.11.0 | 8 failed, 381 passed, 7 skipped in 179.90s |
| 1.10.0 | 12 failed, 377 passed, 7 skipped in 169.37s |
| 1.9.0 | 12 failed, 377 passed, 7 skipped in 188.53s (json/jsonb, numeric, crash tests) |
| 1.8.0 | 182 failed, 207 passed, 7 skipped in 198.52s |
| 1.3.0 | 182 failed, 207 passed, 7 skipped in 335.56s |

The failures are the same tests in every run, so they are not load noise. The floor stays 1.13.
The shakedown host that ran the postgres path on adbc 1.9.0 did not run these tests.

## pynacl (others locked), 3.11

| Version | Result |
|---|---|
| 1.6.2 (locked) | 389 passed, 7 skipped |
| 1.5.0 | 389 passed, 7 skipped in 159.30s |

## duckdb (others locked), 3.11

| Version | Result |
|---|---|
| 2.0.0 (locked) | 389 passed, 7 skipped |
| 1.5.0 | 389 passed, 7 skipped in 178.12s (whole suite); `tests/test_file.py` 34 passed also on 1.5.6 |
| 1.4.5 | `tests/test_file.py` fails: `This relation does not contain a column by the name of 'to_arrow_reader'` |
| 1.4.4, 1.4.0, 1.3.0, 1.2.0 | the same (`tests/test_file.py` only) |
| 1.1.3 | `Catalog Error: Copy Function with name xlsx does not exist!` (34 setup errors in `tests/test_file.py`) |

Below 1.5.0 only `tests/test_file.py` was run, to find the boundary; the whole suite ran on the new floor. 1.5.0 is
8 months old: the first version that works, not the two-year mark.

## arrow-odbc (others locked), tests that need psqlODBC ran in a Linux arm64 container, 3.11

macOS runs skip the odbc tests, so the evidence is `tests/test_odbc.py` in the `tests/odbc` image, with the other
dependencies locked.

| Version | Result |
|---|---|
| 10.7.0 (locked) | 7 passed, 1 skipped |
| 10.0.0, 9.3.7, 9.3.4, 9.3.3, 9.3.0 | 7 passed, 1 skipped (9.3.0: in 27.81s) |
| 9.2.0 | 1 failed, 6 passed, 1 skipped in 16.17s (`'module' object is not callable`, `rowvioli list` on an odbc source) |
| 9.0.0, 8.3.9, 8.3.5 | 1 failed, same cause |
| 8.0.2 | whole suite on macOS 389 passed, 7 skipped in 180.67s (odbc skipped); on Linux arm64: no wheel, a source build needs Rust and fails |

Wheels for Linux arm64 start at 8.1.1 (not 8.3.1, 8.3.2); that alone would have made the floor 8.3.5, and
the test failure made it 9.3.0.

## httpx (others locked), 3.11

| Version | Result |
|---|---|
| 0.28.1 (locked) | 389 passed, 7 skipped |
| 0.28.0 | 389 passed, 7 skipped in 180.68s |

The floor is already 0.28 (0.28.0 is two years old: stop).

## Voided runs (repeated)

Runs with many setup errors or failures in `tests/test_work.py` that did not recur alone: the first baseline (3.11,
`4 failed, 296 passed, 89 errors`, while two copies of my own script ran at once and killed each other's
containers), the second baseline (`2 failed, 79 errors`; Docker's disk was shared by several suites), and the first
runs of pynacl 1.5.0, duckdb 1.1.3, arrow-odbc 8.0.2, httpx 0.28.0 and pyarrow 19.0.0 (`22` to `237` errors), taken
while other agents' suites ran. `tests/test_rest.py` and `tests/test_crashes.py` passed alone (`50 passed`) where the
baseline had errored. Every number in the tables above is from a repeat with Docker's disk at 6 GB free or more,
with no other suite of mine running. Two earlier odbc Linux runs were void too: `uv pip` could not find the
environment in the container, so they ran the locked versions.

## Not tested

- Python 3.12 (only between the two tested; CI covers it now), 3.14 (not in the CI matrix; pyarrow 18 has no wheel
  there, pyarrow 19 and arrow-odbc 9.3.0 were not checked on 3.14).
- Windows and macOS x86_64; Linux x86_64 (CI will: the wheels exist for the floors, not run here); odbc on macOS.
- Linux arm64 ran only `tests/test_odbc.py`; the rest of the suite ran on macOS arm64.
- adbc-driver-manager at a floor (it is transitive); old versions between the tested ones, assumed monotone.
- Each dependency was lowered alone on 3.11 only; on 3.13 only the combined floors ran.
