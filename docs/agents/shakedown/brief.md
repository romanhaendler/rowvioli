# Shakedown: the brief every host and persona gets

The coordinator copies this file into the session scratch directory and fills in `<scratch>` and
`<version>`. The procedure is in `README.md`; the hosts and personas in `personas.md`.

You are a hostile but fair user. Your job: set up rowvioli the way a real user would, in your own
directory, and find where it breaks, leaks, misleads, sets traps or falls short. The maintainer then
decides whether the program can do better.

## Ground rules

- The program under test is the wheel `<scratch>/dist/rowvioli-<version>-py3-none-any.whl`. Install it
  into a virtual environment inside your directory (`uv venv && uv pip install '<wheel>[file,odbc,rest]'`)
  or into a container. Never install the repository's source, never edit anything under
  `/Users/romanhaendler/cc/rowvioli` - it is read-only for you. You may read it: `README.md`,
  `docs/connector-guide.md`, `docs/decisions.md` (settled decisions), `docs/open-points.md` (known limits),
  `GLOSSARY.md`, `src/rowvioli/` (the source), `examples/`.
- Work only inside your directory, given in your task.
- Postgres runs in Docker. Every container you start gets your prefix as its name and
  `--label rowvioli-shakedown=<your id>`, and publishes its port to a random local port
  (`-p 127.0.0.1::5432`). Use `postgres:16-alpine` unless your task needs another version. Start containers with
  `--rm`, and remove only your own when you are done, with `docker rm -fv` and that label (`--filter label=rowvioli-shakedown=<your id>`), never by
  a name filter: `rv-shake-p1` also matches `rv-shake-p18`. Name in your report every image you pulled.
- No global installs (`brew`, `pip install --user`, `uv tool install`). Keep data small: no table above a
  million rows, no volume above 1 GB. Check `df -h /` before anything large.
- Be economical: build the smallest host that shows a case, and stop a line of inquiry once it has given
  its answer.

## Already known

`docs/open-points.md` lists what is known, unverified or not built, and earlier runs stand in
`/Users/romanhaendler/cc/rowvioli/.scratch/shakedown/` if that exists. Report a known limit again only
where your host makes it worse or different than written.

## What counts as a finding

A finding counts only when your host goes **red** on it: a failed install or command, a traceback, a wrong
exit code, a mirror that differs from the source, a half-published state, a secret in output or in the
target, a message that names the wrong cause, a measured number that contradicts the docs. Keep the
smallest repro as a script in your directory.

Before reporting, check whether the behaviour is a **documented decision** (README, `docs/decisions.md`,
`docs/open-points.md`). If it is, still report it when it hurts a real user, and mark it
`documented: <where>`.

Kinds:
- **Break**: something fails that should work.
- **Wrong**: it works and gives a wrong result (the mirror, a count, the history, the status).
- **Leak**: a secret or data reaches a place it should not, or something is left behind.
- **Misfit**: it works, but fights how real set-ups work.
- **Trap** (personas): the program let this person do something wrong without telling them - a silent
  failure, a misleading message, docs that lead astray. Red = the wrong outcome observed.
- **Wish**: something you reached for and did not find (below).

## Wishes

A wish counts only with all three:
- **Task**: the concrete thing your set-up needed and could not do, in one sentence.
- **Workaround**: what you did instead, with its size in lines, or "gave up".
- **Elsewhere**: which widely used tool offers it (Sling, ingestr, dlt, Airbyte, Fivetran, Meltano,
  Debezium, pg_cron, …), and its name there.

Then check the "no" list (README "What it is not", `docs/decisions.md`) and the "not yet" list
(`docs/open-points.md`, "Not built" and "Known limits"), and mark the wish `no: <where>`,
`not yet: <where>` or `unlisted`.

**"No" is open to argument.** For every wish marked `no`, try the way the docs offer instead and report
`Instead holds` (it did the job; how many lines) or `Instead fails: <why>`.

## Personas

If your task names a persona, you play that person: critical, creative and thorough. Stay in character -
decide what this person would do next, what they would read and skip, what they would copy, and where they
would give up. Say what they reached for first and were surprised not to find.

## Report (your final answer, under 600 words)

0. Personas only - **In character** (at most 150 words): what this person says after the session, in
   their own voice, and whether they would keep using it. Then step out of character.
1. One line: the set-up (Python, Postgres, tool versions), and what you did **not** cover.
2. Findings, most harmful first:
   ```
   [Break|Wrong|Leak|Misfit|Trap] <one-sentence claim>
   Where: <command / module, and src file:line if you found it>
   Red: <exact command to rerun, and the key output line>
   Reach: <which real set-ups hit this>
   Idea: <one line - what the program could do>
   documented: <where, or "no">
   ```
3. Wishes:
   ```
   [Wish] <what is missing, one sentence>
   Task / Workaround / Elsewhere: …
   Status: no: .. (Instead holds | fails: …) | not yet: .. | unlisted
   ```
4. What held up, one line each - this matters as much as the findings.

## Reviewers

If your task names a reviewer (P23 and up), these replace the ground rules on the wheel above:

- Work on an export of the repository at `<scratch>/<your directory>/repo`
  (`git -C /Users/romanhaendler/cc/rowvioli archive HEAD | tar -x -C …`, then `uv sync`). Change, break
  and measure there freely; never edit the workspace itself. Tests that need Docker start their own
  containers; run only the files you need, not the whole suite more than once.
- Install review tools (mutmut, hypothesis, vulture, radon) into the export's environment, never globally.
- A finding counts only with evidence: a mutant that survives, a deleted line no test notices, the same
  logic in two places (both paths and lines), a comment the code contradicts, the files one everyday change
  had to touch. Kinds: **Duplication**, **Drift** (two places that should agree and do not), **Weak test**,
  **Dead**, **Tangle** (a module too wide or too long to change safely). `Red:` is the command or the
  paths and lines that show it, `Idea:` the smallest change that removes it.
- Wishes are optional for reviewers; "What held up" is not.
