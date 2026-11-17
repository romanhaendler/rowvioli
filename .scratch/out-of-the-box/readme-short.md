# A short README: the proposal

Branch `readme-short`. The README had 1129 lines (at 657aab2 of `part-2`) and is the PyPI page. It now has 200: a newcomer reads what the program is, sees the first mirror, and finds a link for everything else. The rest moved to seven pages under `docs/`, text unchanged apart from headings, links and one lead sentence per page.

## The cut

| Page | Answers | Lines | From the old README |
|---|---|---|---|
| `README.md` | What is it, how do I get a first mirror, what is promised, how do I install it, where is the rest | 1129 → 200 | top screen, Try it in a minute, Guarantees and What it is not (with the view for another selection), Further documents |
| `docs/definition.md` | How do I write a source down, which settings exist, what does `apply` refuse | 55 | Defining a source |
| `docs/loading.md` | When is a table loaded, what does a run do, which checks stop it, what do I do by hand, how do workers share the work | 281 | Overview, When a table is loaded, A run (with How the program works, Checks, What a person does by hand), Workers |
| `docs/target.md` | What is in the target, how do I read history, how is it compared and published, how does Postgres count, what happens on failures | 197 | Target schema (split: a new heading "History"), Comparing in the target, How Postgres counts, Failures |
| `docs/connections.md` | How is a connection written, encrypted, stored; TLS; keys; rotation; what it protects against | 105 | Connections |
| `docs/commands.md` | What does each command do and need, `apply` in detail, the answer and exit code of `run` | 69 | Commands |
| `docs/operation.md` | How do I run it: the definition's repo, a worker as a service and its log lines, the target and its rights as SQL, deploying under load | 134 | Operation |
| `docs/connectors.md` | Which connectors exist with their options, licences, a custom connector, column types | 132 | Connectors (with Types) |

Within a page the old `###` subsections became `##` where the page title replaced the section heading, so every old anchor slug still exists, on its new page. Links between pages are relative; the README's links are absolute GitHub URLs.

## Merged with the fix round

`out-of-the-box` at cd32b1b changed eleven README lines after this branch was cut. Each went to where its text now lives: the `work` line of the start (README), the `__history` sentence and the near-miss `type` rule (`definition.md`), the second machine's copy of `worker.key` ("Where the keys live", `connections.md`), the `run` row, the target address with a second `@`, the key file message, `apply`'s reset and its near-miss list (`commands.md`), the `file` pattern limits and JSON numbers (`connectors.md`). The pages were cut again from the new README with the same line ranges, so their text is the fix round's word for word. The README's "Operation and security" now says a worker brings "a copy of `worker.key`", in line with the new start. No new code comment points at the README.

## Merged with part-2

`part-2` at 657aab2 added 106 changed or new README lines. The pages were cut again from its README with the line ranges moved to its headings, so every passage sits where its section now lives, word for word: taking over existing tables, the history sentences and the query on the change log (`target.md`); nightly tables, the checks table with its column "Runs", zero rows with `max_delete_share = 1.0`, the `numeric` recipe under "What a person does by hand" (`loading.md`); the consumer's rights on the status, the worker's lines (`operation.md`); options a connector does not know, `numeric(p,s)` under "Types" (`connectors.md`); the dead run's row (`target.md`, "How Postgres counts"). Two passages stay in the README by the owner's decision or their place: "Try it in a minute", in full, after "That is the whole usage" (`tests/test_try_it.py` reads its shell block from `README.md`), and the view for another selection, which follows "What it is not". New comments that named the README now name the page (`connectors/postgres.py`, `tests/test_numeric.py`; the test's function name still says `readme_recipe`, left as is since names are test logic), and `CHANGELOG.md`'s pointer to "What a person does by hand". The changelog has a line for the short README under "Unreleased".

The owner decided that the personas who read "only the README" (P1, P4's agent, P20) read the README and the pages it links to; `personas.md` says so, and `brief.md`'s list of what a shakedown agent may read names those pages too, or the personas could not open them.

## What the README keeps, and why

- **Verbatim:** mascot, version note, the statement, the example definition, the four commands, the status output, "That is the whole usage", "Try it in a minute", the two ideas, Guarantees and "What it is not" with the view for another selection. This is the aha: one file, four commands, one view.
- **New, short:** "Install" (Python 3.11+, `uv tool install` / `pip install`, the extras `file`, `odbc`, `rest`; nothing like it existed, the facts come from `docs/package.md`, "A worker" and "Two ways to get a connector"). Then one paragraph each for "Defining a source", "When a table is loaded", "Connectors", "Operation and security" and "Commands", each saying what exists and linking its page. "Connectors" shows the one-line `read` signature, because the contract being one function is itself a selling point.
- **The Web UI sentence** ("There is none; everything a UI needs is in `_rowvioli`...") stays in the README under "Operation and security", reworded to "There is no web UI; ...".
- **Further documents** lists the new pages first, then the old rows. The "Measurements" section shrank to its `bench/bench.py` sentence under the table.
- **Dropped:** the "Contents" list (navigation of the long page) and the first half of "Measurements" (see duplicates).

## Duplicates found (all kept except the first)

1. "Measurements": "Set-up, numbers and limitations are in docs/measurements.md" said the same as the Further documents row for it ("All measurements with set-up and limitations"). Kept the row, dropped the sentence; the bench sentence stays.
2. Near-miss settings and types: `definition.md` (paragraph after the settings table) and `commands.md` ("It fails rather than guess") both say that `max_agee` and a `type` near `postgres` fail `apply`.
3. A pooler in session mode only: `operation.md` ("The target", bullet) and `target.md` ("Failures", last paragraph, with the check and its measurement).
4. A missing connector names the worker: `loading.md` ("Rules", "All workers on one target are equipped alike") and `target.md` ("Failures" table row). Also "Providing the connectors is the operator's task" (`loading.md`) and "Installing connectors on the workers is the operator's task" (`connectors.md`).
5. "Two ways to get a connector" (`connectors.md`) repeats the table under "Modularity" in `docs/package.md`.
6. Already known (`.scratch/shakedown/code.md` 4): the opening of `docs/connector-guide.md` restates "Licences".
7. The README's "Install" and "Connectors" both name the extras; the README's short sections repeat facts of the pages they link by design.

## References fixed

- Code comments and two test docstrings that said `README "Failures"`, `"A run"`, `"Types"` and so on now name the page (`src/rowvioli/load.py`, `target.py`, `work.py`, `connectors/postgres.py`, `sql/claimable.sql`, `sql/schema.sql`, `tests/test_crashes.py`, `tests/test_history.py`). No logic changed.
- Present-tense pointers in `docs/decisions.md` (the rights, "What a person does by hand", the history advice), `docs/measurements.md` (the "Failures" table, the index recommendation), `GLOSSARY.md` (terms change here, in the README and in `docs/`), `docs/agents/shakedown/personas.md` (the rights table).
- `bench/bench.py` said it reproduces "the measurement table of the README"; that table was already gone before this branch. It now names `docs/measurements.md`.
- Nothing linked into the README with an anchor (`grep` for `README...#` over the repo: none). Past-tense mentions in `docs/decisions.md` and every mention under `.scratch/` (tickets, findings with old README line numbers) are history and left as they are.

## Unsure

- **Where Overview and Workers live.** Both are in `docs/loading.md`, which makes it the longest page (281). A separate "how it works" page would split it but add a page.
- **"How Postgres counts" in `target.md`** rather than in `loading.md`: it is about the claim, but its content is locks inside the target. Followed the brief's suggestion.
- **README length 200**, of which "Try it in a minute" is 59. The Overview diagram was moved because mermaid does not render on PyPI.
- The README's GitHub links to the new pages resolve only once the branch is on `main`.
