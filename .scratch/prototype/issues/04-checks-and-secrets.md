# Checks, failure reasons, no secret leaks

Status: ready-for-agent
Blocked by: 03

Spec: `.scratch/prototype/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prior art: `experiments/`.

## What to build

Spec "One run" checks, unknown connector type, wrong private key, ciphertext swapped between sources, scrubbing connection values from every reason, `runs` row and output. User stories 27, 28, 38-40, 43, 44.

## Acceptance criteria

- [x] Spec tests 15, 16, 17, 18 pass.

## Comments

Observations for spec question 4 (impl-04, adbc-driver-postgresql 1.13.0, Postgres 16):

- **Refused login.** A wrong password gives `IO: [libpq] Failed to connect: connection to server at "...", port ... failed: FATAL:  password authentication failed for user "..."`. Neither the password nor the URL is in it. The run fails after the claim like any other error, so the table goes into its pause with that reason.
- **But libpq quotes parts of a URL it cannot parse.** A password with a `%` that is not percent-encoding (`Prozent%zz-4711`) gives `invalid percent-encoded token: "Prozent%zz-4711"`: the password alone, not the whole value. Removing "every value of the connection" (the spec's wording) would not have caught it, because the value is the whole URL. The scrubbing therefore removes every value and, for a value that is a URL, its password. A password with an unencoded `@` is split by libpq, and a part of it can appear as a host name ("could not translate host name"); that is not removed (shortcut in `load.py`). The documents should say that a password placed into a URL must be percent-encoded, or `apply` should encode placeholder values inside a URL's user info.
- **The driver loses `varchar(n)`.** A source column changed from `text` to `varchar(20)` arrives as `text` in the staging table, so the check "columns of the staging table equal the mirror's" cannot see it. Only changes the Arrow type shows are detectable (for example `int` to `bigint`, a new or dropped column). Precision and scale of `numeric` are lost the same way (ticket 03). The README's "a column ... has changed its type" holds only for types the driver distinguishes.
- **`numeric` from the control connection** comes back as a string: `sources.max_delete_share` is read with `::float8`.

Deviations from README / GLOSSARY / decisions / spec:

- Without the duplicate check a duplicate key did not fail at all: the diff turned the second row into an update, and one of the two rows silently went missing. The check is necessary, not only a nicer reason.
- Order of checks: zero rows, columns, key against the mirror's primary key, null key, duplicate key, then the diff, then `max_delete_share` (it needs the count of deletions from the diff). The README lists the delete share among the checks of step 4; it is computed after step 5 here, still before publishing.
- `max_delete_share` for a table without a key counts the shrinkage: `(rows in mirror - rows read) / rows in mirror`. For such a table every run "deletes" every row, so the README's "rows would disappear" cannot mean the deletions.
- Columns are compared by name and type, ignoring their order. A reordered source table passes, because the program copies by name. (Review: the change-log insert filled columns by position until impl-review, so swapped columns of one type landed in each other's log column; now named, tested in `test_run.py`.)
- A table without a key whose definition later gets a key fails with "the key [...] differs from the mirror's primary key []", and the other way round. The README says a changed key is never converted.
- Reasons: `connector "nosuch" is not installed on worker host:pid`, `the connection of source erp cannot be decrypted on worker host:pid: <PyNaCl text>`, `the connection of source crm was sealed for another source` (from ticket 02, now also wrapped as "cannot be decrypted"), `the source delivered zero rows`, `the columns differ from the mirror's`, `a key column of ("k") is null`, `a key combination of ("k") occurs twice`, `67 % of the rows would be deleted`. Scrubbed values become `***`.
- Scrubbing happens in the run's one failure path, so it covers the reason in `tables`, in `runs` and in the JSON answer. It cannot cover a traceback of a run process that crashes (stderr is inherited); none occurred in the tests. A connection that cannot be opened is not known, so nothing of it can be in a reason.
