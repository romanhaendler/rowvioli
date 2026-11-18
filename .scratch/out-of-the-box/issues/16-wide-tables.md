# 16: A wide table is read slowly from the source

**Blocked by:** none

**Status:** needs-triage

**Model:** Opus (the question is whether a different read is possible; Sonnet once it is decided)

From the measurement of 2026-11-17 (`docs/measurements.md`, section 15; program at commit 4705418).

## Evidence

A whole `rowvioli run` of 100,000 rows of 300 columns takes 10.9 to 11.8 s when nothing changed (2.5 to 2.8
million cells a second). The run is dominated by the statement `COPY ... _stage ... FROM STDIN` on the
target: 8 to 9 of the 11 one-second samples of `pg_stat_activity`, at 300,000 rows 26 to 28 of 38 to 45.
That statement mostly waits for the client; the client is waiting for the source.

The read alone, `SELECT * FROM wide` through the same ADBC driver with every batch thrown away
(`fetch_record_batch`, three runs): 6.6 to 6.8 s. The same data from the same server through `psql`:

| Read of the wide table (100,000 rows, 300 columns) | Seconds |
|---|---|
| `COPY wide TO STDOUT` (text) | 1.5 to 2.0 |
| `COPY wide TO STDOUT (FORMAT binary)` | 5.6 |
| ADBC `fetch_record_batch` | 6.6 to 6.8 |

On the narrow table (10⁶ rows, 8 columns) the read through ADBC is 1.1 s of a 4.2 s run and costs 7.3 million
cells a second, against 4.5 million on the wide one. So about 60 % of a run on a wide table is the driver
reading and converting from the source's binary format, and the text COPY of the server is almost
four times faster than the binary one. The diff (1 to 2 samples at 100,000 rows) is small by comparison and grows a
little faster than the rest at 300,000 rows (8 to 13 samples).

## What to find out

- Is the time in the server (producing binary), in the driver (converting to Arrow), or in the pipe? A
  profile of the 6.7 s decides.
- Is there a cheaper read for a Postgres source: a text COPY parsed by us, a second connection reading by
  key range in parallel, or a newer driver version?
- It is not clear that this is worth a change: 11 s for 100,000 rows of 300 columns is no scale problem for
  a table loaded every few minutes. It becomes one at some 10⁶ rows of this width (extrapolated, not
  measured: about 2 minutes).

Out of scope: the other connectors (`odbc`, `rest`, `file`), which were not measured at this width.
