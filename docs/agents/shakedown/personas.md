# Shakedown: the hosts and the personas

Each entry is one subagent's task, handed over together with `brief.md`. **Hosts** test a set-up;
**personas** are people who use rowvioli and judge it; **reviewers** judge the code. "Run" names the run
that used the entry last; an entry without one has not run yet. Add an entry when a run finds a blind spot;
drop one that stops finding anything.

## Hosts

### H1 Install and target
The wheel with `[file,odbc,rest]` into a fresh `python:3.11-slim` container (the floor) and with the
newest Python on the Mac; `rowvioli --help` and every subcommand's help; the quickstart flow of the README
step by step. Targets: the oldest Postgres still supported upstream and the newest; a target user with only
the rights the table in `docs/operation.md` names (no superuser, no `CREATE` on the database beyond what `init` needs);
pgbouncer in session mode in front, and transaction mode to see that it fails with a clear message. Run: 2026-11-24.

### H2 Hostile source data
A Postgres source with what real systems hold: a table that is empty, one with a NULL or a duplicate in
the key, identifiers with capitals, spaces, quotes, umlauts and SQL keywords, a column named `_op` or
`_loaded_at`, `json`, `xml`, `bytea`, arrays, `numeric` beyond 38 digits, `timestamptz` and `timestamp` in
odd time zones, `interval`, `NaN` and infinity, a 300-column table, a type changed between two runs, a
key column dropped. Every case must end in a correct mirror or a reason a person understands; nothing may
be half published. Also a `file` source (CSV with a BOM, `;`, quoted newlines) and a `rest` source against
a local HTTP server that answers slowly, with a 500, and with a changed shape. Run: 2026-11-24.

### H4 Operation
`work` under systemd-like stops (SIGTERM, then SIGKILL after a timeout), the target restarted during a
run, the network to the source cut (`docker network disconnect`), the clock of the worker container set
forward and back, two definitions applied from two places at once, a full disk on a small volume only. Run: 2026-11-24.

### U1 Upgrade from the released version
A fleet on the last released wheel (the coordinator builds it from its tag beside the wheel under test):
a target with tables that load, tables stuck on each reason the old version stops with, a primary key a
person changed by hand, a key changed in the definition, grants for a worker and a consumer. Then the
upgrade as `docs/operation.md` says it, and as people get it wrong: `init` as the wrong role, an old worker
left running, the grants forgotten. Every table must load or give a reason with its way out, the history at
every moment before the upgrade must stay what it was, and the change log replayed must give the mirror. Run: 2026-11-24.
`tests/test_upgrade.py` does this with 0.4.1 in the suite (its source from the tag, run with the suite's
libraries); the host adds what the suite has not: the wheel as released, a fleet over days, an old worker left
running, a worker's role of least rights. When 0.5.0 is released, the test moves to its tag.

## Personas

### P1 Lena, total beginner
Has written SQL for reports, never run an ETL tool. Reads only the README, the pages under `docs/` it
links to and the quickstart, copies the examples. Makes the beginner's mistakes on purpose - a typo in a
TOML key, `max_age = "1 hour"`, a table without `key`, a key that is not unique, `apply` forgotten after a change, `run` before `init`, the
environment variable missing or misspelt, the wrong directory to `apply`, a source password with `@` and
`/` in it - and judges whether each one gets a message that tells her what to do. Time to the first
mirrored table. Run: 2026-11-15.

### P3 Dr. Petra Brandt, staff engineer
Evaluates for a five-year commitment and trusts no README claim until measured: every line under
"Guarantees" and every number in `docs/measurements.md` checked against the wheel; upgrade risk; escape
hatches for month 3 (a table that needs a `WHERE`, a source the connectors do not cover).

### P4 Jonas, vibe coder
A product owner whose coding agent may read only the README, the pages under `docs/` it links to
(`docs/connector-guide.md` among them) and `--help`. Five
plain-word requests: mirror our shop database every 15 minutes, add a CSV that lands in a folder daily, add
a REST API with paging, write a connector for a source rowvioli does not have (SQLite), show me the state
of every order as of last Monday. For each, where the docs were wrong, missing or misleading. Run: 2026-11-18.

### P16 Migrating team
Moves a working mirror from cron and hand-written scripts to rowvioli: builds the
"before" for real first, then the effort per table, what has no counterpart, which habits break.

### P18 Security reviewer
Secrets in output, logs, error texts and `_rowvioli` tables (source passwords, the target password, the
private key), the encryption of connections, SQL injection through table and column names that come from
a source or the definition, the rights a worker and the `apply` pipeline really need against what the
README says, what a connector or an `options` value can reach, supply chain (dependencies, licences). Run: 2026-11-24.

### P20 Consumer
An analyst who only reads the target: the mirrors, `<table>__log` and `<table>__history`. Can she answer
"what changed yesterday", "the state as of a moment", "when was this loaded" from the README and the
pages it links to alone, and are the answers right? Does a reader ever see a half state while workers run? Run: 2026-11-24.

### P22 ELT specialist
Ten years of Fivetran, Airbyte, dlt, Sling and ingestr in production; judges rowvioli on its feature set
alone. A matrix of 30-50 features (sources, incremental modes, deletes, schema drift, history, monitoring,
secrets, scale, operation), each claim verified on the wheel; the gaps that would make him reject it,
ranked by how often real teams need them; for which teams rowvioli is enough. Answers the open point
whether Sling or ingestr already cover most of this.

## Reviewers

Reviewers judge the repository, not the wheel. They work on an export (`brief.md`, "Reviewers") and take
`CLAUDE.md`, `GLOSSARY.md` and `docs/decisions.md` as the bar the code set itself.

### P23 The maintainer's successor
Takes the repository over tomorrow, alone. Starts from the README and `GLOSSARY.md` only, then makes four
everyday changes in the export and counts what each costs: a new check before publishing, a new column in
the status view, a new option for the `file` connector, a new reserved column name. Files touched, places
that had to agree, tests that broke for a reason she could not see.

### P24 Test-quality auditor
Asks of every test: would it fail if the behaviour broke? Mutation testing (mutmut) on the pure modules
(`interval`, `quote`, `settings`, the checks), deleting a line of source to see whether anything goes red,
property-based tests (hypothesis) for the seams (quoting round-trips, interval parsing), and which tests
cost the most time for the least.

### P27 Bert, the deleter
Believes the best code is the code that is gone. Lists what could go without a user noticing: options only
their own test uses, branches for states that cannot occur, a helper kept for one caller, docs that repeat
another doc, tests that prove the same thing twice. Each with the lines it saves and the proof no one
depends on it (the tests, the docs, the examples); weighs it against `docs/decisions.md`. Run: 2026-11-15.
