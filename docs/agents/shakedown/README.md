# The shakedown

A **shakedown** installs the built package the way someone else would and tries to break it there: on a
fresh machine, against targets and sources that are not the test suite's, and in the hands of people who
are not the maintainer (a beginner, a coding agent, a security reviewer). The test suite runs against the
checkout; this runs against the wheel, in the user's set-up, and finds what the suite cannot see.

Taken over from umriss (`~/cc/umriss/docs/agents/shakedown/`), cut down to what fits a program that
mirrors tables: no browsers, no design, no touch.

Run it before a release, before a change to a dependency floor or the target's schema, and otherwise every
few minors. Findings stand in `.scratch/shakedown/`.

## Steps

1. **Check the disk.** `df -h /` and `docker system df`; note the images and volumes that are there
   (`docker images`, `docker volume ls -q`). Tests once filled the disk.
2. **Pack.** `uv build --out-dir <scratch>/dist` (never into the repo). Copy `brief.md` to `<scratch>` and
   fill in `<scratch>` and `<version>`.
3. **Pick.** Take the hosts and personas from `personas.md` that the change touches; a full run takes all.
   Each becomes one subagent with: the path to the brief, its entry from `personas.md`, its own directory
   `<scratch>/<id>`, and its own container prefix `rv-shake-<id>`.
4. **Dispatch in one wave of at most six**, on Sonnet (the work is specified; see CLAUDE.md), reviewers
   included. Keep the Mac awake (`caffeinate -i`) while they run.
5. **Verify.** The coordinating session reproduces every finding it writes down as a defect, or confirms it
   in the source, and marks it ✓. A subagent's report is a lead, not a fact.
6. **Write down.** One file per area under `.scratch/shakedown/` (`install-target.md`, `source-data.md`,
   `operation.md`, `first-use.md`, `security.md`, `code.md`) plus `wishes.md` and a `README.md` with the five
   that matter most, each with
   `Status: needs-triage`, the findings ranked, the wishes with their three proofs, and what held up. On a
   rerun, compare with the last run: what is fixed, what is new, what came back.
7. **Triage.** The files go through the triage labels (`docs/agents/triage-labels.md`); a fix starts from
   the host's red as its first test.
8. **Clean up.** Remove every container with the label `rowvioli-shakedown`
   (`docker rm -fv $(docker ps -aq --filter label=rowvioli-shakedown)`; `-v`, or every Postgres container
   leaves its anonymous volume behind), the images and the dangling volumes the run added (by `CreatedAt`)
   and nothing else, the virtual environments under `<scratch>`. Then `df -h /` again.

## Cost

A full run is six Sonnet agents and one Opus session that verifies. Keep it there: a persona that finds
nothing twice in a row is dropped, and a new entry replaces one rather than adding to the wave. Agents
underreport what they skipped: the brief asks for "held up" and "not covered"; read them before
dispatching more.
