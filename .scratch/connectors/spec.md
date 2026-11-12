# Connectors: `odbc` and `rest`, and what rowvioli may ship

Status: resolved

## Problem Statement

rowvioli 0.1 reads from PostgreSQL and from files. The sources the owner actually has to mirror are SQL Server, Informix and HTTP interfaces. The README already describes `type = "odbc"` and `type = "rest"`, and its first example is an ODBC source, but neither connector exists (`docs/open-points.md`, "Not built").

Before building them the owner asked: how can more connectors be built without violating any licence? Today the answer is spread over one decision (16, no Docker image because of vendor drivers) and one table (`docs/package.md`, "Dependencies"). Nothing says what a connector's code may be taken from, which dependencies an extra may have, or where a connector goes that needs a GPL library or a vendor SDK. Whoever adds the fifth connector has no rule to follow and nothing that stops a mistake.

## Solution

One sentence carries it: **rowvioli ships only code written for it and dependencies under a permissive licence; everything under another licence is installed by the operator or lives in a separate package.**

The two connectors follow from it without a single new licence question:

```toml
# sources/erp.toml
[erp]
type    = "odbc"
max_age = "1h"

[erp.connection]
string = "Driver={ODBC Driver 18 for SQL Server};Server=sqlsrv01;Database=erp;UID=reader;PWD=$ERP_PASSWORD"

[erp.tables]
"dbo.Customers" = { key = ["CustomerNo"] }
```

```toml
# sources/weather.toml
[weather]
type    = "rest"
max_age = "1h"

[weather.connection]
url   = "https://api.example.org"
token = "$WEATHER_TOKEN"

[weather.tables.readings]
key     = ["station", "time"]
path    = "/v1/readings"
page    = "page"
columns = { station = "text", time = "timestamptz", temp = "float8" }
```

- `pip install "rowvioli[odbc]"` brings arrow-odbc (MIT). The vendor's ODBC driver is installed by the operator, who accepts its licence. rowvioli never contains it.
- `pip install "rowvioli[rest]"` brings httpx (BSD-3-Clause) and needs nothing else.
- A connector that cannot keep the sentence above (it needs a GPL library or a vendor SDK) is a separate package with its own licence, registered through the entry point that exists since 0.1.

## User Stories

### What rowvioli may ship

1. As the owner, I want one decision that says what the package may contain, so that every later connector is judged by the same sentence.
2. As a contributor, I want to read that a connector's code is written from the source's public documentation and never taken or ported from another project's connector, so that no copyleft or source-available code enters an MIT project.
3. As a contributor, I want to read which licences a dependency of the core or of an extra may have (MIT, BSD, Apache-2.0), so that I can check a library before I propose it.
4. As a contributor, I want to read where a connector goes whose library is under GPL, AGPL or a vendor licence, so that I build it as a separate package and do not ask for it in the core.
5. As the owner, I want every dependency of the core and of every extra to have a row with its licence in the dependency table, so that the state can be read in one place.
6. As the owner, I want the test suite to fail when a dependency has no row in that table, so that a forgotten row is caught on the push that adds the dependency.
7. As an operator, I want the README to say that vendor drivers are installed by me and under the vendor's licence, so that I know which terms I accept and that rowvioli accepts none for me.
8. As a user of the package, I want the MIT licence of rowvioli to cover everything `pip install rowvioli` and its extras put into the package itself, so that I can use and pass it on without reading a second licence for rowvioli's own code.
9. As the owner, I want product names used only to say what a connector reads (`type = "odbc"`, "SQL Server" in a table), and no logo in the repo, so that no trademark is touched.
10. As the owner, I want no vendor SDK, driver, specification file or example copied into the repo, the package or the example Dockerfile, so that nothing is redistributed (decision 16 extended from the image to everything).

### The `odbc` connector

11. As an operator, I want `type = "odbc"` with a connection field `string`, so that any source with an ODBC driver is attached by its connection string.
12. As an operator, I want a table named as in the source (`dbo.Customers`), so that the definition reads like the source and the target table follows the existing naming rule.
13. As an operator, I want the rows to arrive in chunks bounded in size, so that a table of any length loads with bounded memory, as with `postgres`.
14. As an operator, I want column types to follow from what the driver reports for the table, never from the first rows, so that they cannot flip between two runs.
15. As an operator, I want decimals to arrive as `numeric`, dates as `date`, timestamps as `timestamp` and text as `text` in the target, so that the mirror can be joined and compared without casts.
16. As an operator, I want `rowvioli list erp` to print the tables of an ODBC source with their primary keys where the source has `INFORMATION_SCHEMA`, so that I can paste the tables block for SQL Server.
17. As an operator of a source without `INFORMATION_SCHEMA`, I want `list` to fail with a sentence that says so, so that I know to write the tables block by hand and that loading is not affected.
18. As an operator, I want a run to fail with the driver's message when the driver named in the string is not installed, with the worker named as for a missing connector, so that I see which machine is not equipped.
19. As a security officer, I want the password inside the connection string never to appear in a reason, a line of a worker or the output of `list`, so that the promise of decision 32 holds for ODBC, where drivers like to quote the string back.
20. As a security officer, I want a table name that is not a plain dotted name to be refused before any query is sent, so that the definition cannot carry SQL into the source.
21. As an operator who loads only from Postgres, I want to install neither arrow-odbc nor an ODBC driver manager, so that the core stays small.
22. As an operator, I want a source of `type = "odbc"` on a worker without the extra to fail as any missing connector does, naming the worker, so that there is one wording for "not equipped".

### The `rest` connector

23. As an operator, I want `type = "rest"` with the connection fields `url` and `token`, so that an HTTP interface is attached without writing code.
24. As an operator, I want the option `path` per table, appended to `url`, so that one source holds several endpoints.
25. As an operator, I want the option `columns` to name every column with its type, so that the schema is in the definition and never guessed.
26. As an operator, I want the types `text`, `int8`, `float8`, `bool`, `date`, `timestamp` and `timestamptz`, written as PostgreSQL writes them, so that I already know the words.
27. As an operator, I want a field of the response that `columns` does not name to be dropped and a named field that is missing to be null, so that an interface that grows does not break the load.
28. As an operator, I want a value that does not fit its named type to fail the run with the column's name, so that the mirror never holds a silently bent value.
29. As an operator, I want the option `page` to name a query parameter that counts from 1 until a page comes back empty, so that a paged interface is read to its end.
30. As an operator, I want a table without `page` to be one request, so that a small endpoint needs no option.
31. As an operator, I want each page to be delivered as one chunk, so that memory is bounded by the page size of the interface.
32. As an operator, I want the token sent as `Authorization: Bearer`, and no header when the connection has no token, so that open and protected interfaces both work.
33. As an operator, I want an answer other than success to fail the run with the status code and the path, so that I see what the interface said.
34. As a security officer, I want the token never to appear in a reason or a line, so that decision 32 holds for `rest`.
35. As an operator, I want a response that is not a JSON array of flat objects to fail the run with a sentence that says what was expected, so that I know at once that this interface needs a custom connector.
36. As an operator, I want `rowvioli list` on a `rest` source to say that the connector cannot list tables, as it does for any connector without that function, so that there is nothing special to learn.
37. As an operator who needs another kind of paging, a wrapped response or another header, I want the README to point me to the custom connector of ten lines, so that the shipped one stays small.

### Documents

38. As a reader of the README, I want "Connectors" to say that 0.2 ships `postgres`, `file`, `odbc` and `rest`, with the options of `odbc` and `rest` described once, so that the document matches the program.
39. As a reader of the README, I want a short paragraph "Licences" under "Connectors" with the carrying sentence and its three consequences, so that I find the rule where I look for connectors.
40. As a reader of the decisions, I want the new decision under the next number with what was rejected, so that nobody bundles a driver or adds a GPL dependency later without knowing the reason.
41. As a reader of `docs/package.md` and `docs/open-points.md`, I want them to say that `odbc` and `rest` are built and that the version is 0.2, so that the status documents stay true.

## Implementation Decisions

### What rowvioli may ship

- **A new decision is appended to `docs/decisions.md`** under the next number (38): "rowvioli ships only code written for it and permissive dependencies". It states four consequences:
  1. A connector's code is written from the public documentation of the source. Nothing is copied or ported from other projects' connectors, whatever tool does the porting.
  2. A dependency of the core or of an extra is under MIT, BSD or Apache-2.0. It has a row in the dependency table of `docs/package.md`.
  3. Vendor drivers, SDKs and specification files are in no package, no repo file and no image. The operator installs them (extends decision 16).
  4. A connector that cannot keep 1 to 3 is a separate package with its own licence, outside this repo, registered through the entry point group `rowvioli.connectors` (decision 27).
- **Rejected in that decision:** bundling drivers for convenience; a GPL library behind an optional extra (whether the MIT code stays untouched by it is disputed, a separate package ends the dispute); a licence scanner as a CI service (one small test over the table is enough); a contributor licence agreement.
- **The decision says that it is the project's rule, not legal advice.** A connector for a source whose SDK is under a vendor licence is looked at by a lawyer before it is published, even as a separate package.
- **One test guards the table.** It reads the dependencies of the core and of every extra from the project file and fails if one has no row in the dependency table. It checks that the row exists, not what the licence is: the row is written by a person who looked.
- **Product names** appear as plain words only. No logo, no vendor file.

### The `odbc` connector

- **A shipped connector**: code in the core package, the dependency arrow-odbc behind the extra `odbc`, registered in the entry point group like `postgres` and `file`. The extra joins the development dependencies.
- **Connection field `string`**, the ODBC connection string, as the README already shows.
- **`read`** sends `SELECT * FROM <table>` and returns arrow-odbc's batch reader. The chunk is bounded by bytes through arrow-odbc's own limit, set to about the 16 MB the `postgres` connector delivers. The schema is the one arrow-odbc derives from the driver's column descriptions.
- **The table name goes into the query as written**, after a check that every dotted part consists of letters, digits and underscores. It is not quoted, because quoting differs between SQL Server, Informix and others, and a plain name needs none on any of them. Anything else is refused with a sentence that names the rule.
- **Types**: whatever arrow-odbc maps is passed on unchanged where the core can write it to the target. If a type the core cannot write shows up in the tests (as `numeric` did with ADBC, see README "Types"), the connector converts it and the README names it. No mapping is written in advance.
- **`tables`** asks `INFORMATION_SCHEMA.TABLES` and the key columns of primary key constraints, and returns `schema.table` with the key in key order or none. A source without `INFORMATION_SCHEMA` makes `list` fail with one sentence; loading does not use `tables`.
- **Reasons are scrubbed by the existing mechanism.** The connection string is one connection value; the implementation checks that the password inside it is scrubbed too, not only the string as a whole, and extends the existing extraction of connection values if it is not.
- **No driver is named, installed or downloaded by rowvioli.** The example Dockerfile keeps its comment that the operator adds the vendor driver.

### The `rest` connector

- **A shipped connector** behind the extra `rest` with httpx, registered like the others. It has no `tables`.
- **Connection fields `url` and, optionally, `token`.** Options `path`, `columns` and, optionally, `page`.
- **`read`** requests `url` + `path`; with `page` it adds that query parameter, counting from 1, and stops at the first empty array. Each response must be a JSON array of objects. Each page becomes one Arrow batch with the schema built from `columns`.
- **`columns` is required** and maps a name to one of `text`, `int8`, `float8`, `bool`, `date`, `timestamp`, `timestamptz`. Another word fails the run and names the seven. Dates and timestamps are read from ISO 8601 text.
- **Fields**: not named → dropped; named and missing → null; named and not convertible, or nested → the run fails with the column's name.
- **`token`** is sent as `Authorization: Bearer <token>`. An unsuccessful status fails the run with the code and the path, never the full address with its query or a header.
- **Nothing else**: no other paging, no unwrapping of a response, no other authentication, no retries of its own (the pause of the core retries the run).

### Version and documents

- **The version becomes 0.2.0.** Nothing is tagged or published by this spec.
- **README**: "Connectors" (the table, the sentence about versions, the options of `odbc` and `rest`, the new paragraph "Licences"), "Types" if a conversion was needed, and the installation line where it names extras. **`docs/package.md`**: "What goes into 0.1" becomes the state of 0.2 for connectors; the dependency table already has both rows. **`docs/open-points.md`**: `odbc` and `rest` leave "Not built"; JSON files stay. **GLOSSARY**: no new term.

### Who implements

Estimate, to be checked again per ticket (the owner's rule: the smallest model that fits; Fable practically never; Opus reviews at the end).

| Work | Model |
|---|---|
| The decision, the paragraph in the README, the test over the dependency table | Sonnet. Specified and mechanical. |
| The `rest` connector | Sonnet. Small, everything is named here. |
| The `odbc` connector with its tests | Opus. The types, the scrubbing of the string and the driver in CI need judgement. |
| Documents and version | Sonnet. |
| Review of the whole at the end | Opus. |

## Testing Decisions

- **The existing seam, nothing new.** Tests start the commands as real processes and look only at what a user sees: the mirror in the target, the answer of `run`, the output of `list` (`tests/conftest.py`; `.scratch/v0.1/spec.md`, "Testing Decisions"). No test imports a module of the program. Prior art for a connector: `tests/test_file.py`.
- **A good test** states one sentence of this spec and would pass if the connector were rewritten on another library.
- **`rest` is tested against a small HTTP server inside the test** (standard library, a thread), which serves fixed pages and records the requests it received. No container, no network.
- **`odbc` is tested against a free source only**: PostgreSQL through the open psqlODBC driver, with driver manager and driver in a container, nothing installed on the developer's machine. The tests are skipped with a clear message where no driver manager can be had. SQL Server and Informix are not tested: both need the acceptance of a vendor's terms (owner's decision of 2026-11-12, see "Further Notes"). A guide says how to write and test a connector that needs licensed software.
- **The licence rule has one test**: every dependency of the core and of every extra has a row in the dependency table.

What is tested:

1. `odbc`: a table with an integer, a text, a decimal, a date, a timestamp and a null is mirrored with those types and values; a second run after a change in the source records the change in the change log.
2. `odbc`: `list` prints the tables with their primary keys, a table without key without one.
3. `odbc`: a wrong password fails the run, and neither the reason in the status view nor the stderr of `run` contains the password (prior art: `tests/test_secrets.py`).
4. `odbc`: a table name with a quote or a semicolon is refused, and the source received no query for it.
5. `rest`: a paged endpoint of three pages is mirrored completely; the server saw `page=1` to `page=4`.
6. `rest`: without `page` there is exactly one request.
7. `rest`: the named types arrive as those types in the target; an unnamed field is absent; a missing field is null.
8. `rest`: the token arrives as a Bearer header; a 401 fails the run with the code, and the token appears nowhere.
9. `rest`: an unknown type word, a value that does not fit, and a response that is not an array each fail the run with a reason that names the cause.
10. `rest`: `list` says that the connector cannot list tables.
11. The dependency table has a row for every dependency of the core and of every extra.

Disk space: the harness's rule stands: containers and volumes are removed after the session.

## Out of Scope

- JSON files in the `file` connector. Still "later".
- Connectors for MySQL, Oracle, Snowflake, SAP or any other single product. ODBC covers what has a driver; the rest are separate packages under the new decision.
- A query instead of a table name, quoted names with spaces, reading only rows from a timestamp on.
- For `rest`: cursor or offset paging, `Link` headers, wrapped responses, nested objects, other authentication, rate limits, retries inside a run.
- Types for `rest` beyond the seven, including `numeric`.
- An official Docker image, or any image with a driver (decision 16).
- A licence scanner, SBOM, or a check of transitive dependencies.
- A contributor guide or a contributor licence agreement.
- Publishing 0.2 to PyPI.

## Further Notes

- The owner asked on 2026-11-12 how more connectors can be built without violating licences, and then asked for this spec. The answer given: write the code yourself, permissive dependencies only, never ship vendor drivers, everything else as a separate package; build `odbc` and `rest` first because both were planned and neither raises a licence question.
- The licences in the dependency table were named from memory. Whoever implements checks arrow-odbc and httpx on PyPI before adding them and corrects the table if needed.
- (Superseded, see the last bullet.) **For the owner to accept before the `odbc` ticket runs:** the SQL Server container and Microsoft's ODBC driver are used in tests under Microsoft's terms (the container asks for `ACCEPT_EULA=Y`; the Developer edition is free for development and test). Nothing of either is redistributed, so the new decision is kept, but accepting terms is the owner's act and not an agent's. If the owner declines, the `odbc` tests run against another ODBC source and SQL Server stays untested.
- (Superseded, see the last bullet.) The SQL Server image exists for amd64 only. On the owner's Mac it runs emulated or not at all; that is why the `odbc` tests may skip locally and CI is the proof.
- Decided here by assumption, because the skill forbids an interview: `page` as a counting query parameter is the one paging scheme (the README's own example pages this way); the `odbc` table name is not quoted; `tables` for `odbc` uses `INFORMATION_SCHEMA` and so serves SQL Server but not Informix; the version becomes 0.2.0.
- The seam was not confirmed with the owner beforehand. It is the one every earlier spec used, plus an HTTP server inside the test for `rest`.
- The owner's rule applies: one carrying idea, no pile of rules. The measure is that the README needs one paragraph for licences and that the decision has four consequences, each following from the one sentence.
- This is the project's rule, not legal advice.
- **Changed by the owner on 2026-11-12, during implementation:** tests run only against truly free sources, and nothing is installed locally. The `odbc` tests use PostgreSQL through psqlODBC instead of SQL Server; the notes above about `ACCEPT_EULA`, the SQL Server image and CI as the only proof no longer apply. In exchange the owner wants a very good guide on writing a connector that needs licensed software (ticket 05). What was read in the vendors' terms: Microsoft's Developer edition and ODBC driver are licensed to develop and test, Microsoft commits `ACCEPT_EULA=Y` in its own repos, who accepts when a third party runs a workflow is answered nowhere, and benchmark results of SQL Server need Microsoft's written approval; the text of IBM's licence for the Informix Developer Edition and for the Client SDK with its ODBC driver could not be retrieved.
- **As built, differing from the stories:** story 17 has no test (no free source lacks `INFORMATION_SCHEMA`). Story 18: the driver's message is the reason; the worker is named in the row of `runs`, not in the reason. A registered connector whose import fails is reported as one that cannot be loaded, with the error's text.
