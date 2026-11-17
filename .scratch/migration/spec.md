# Migration: `init` brings the bookkeeping schema to the program's version

Status: needs-triage (a draft for the owner; nothing here is decided, the questions at the end are his)

From `docs/open-points.md`, "Not built": migrating the schema from one version to the next. Written
2026-11-18, after 0.1.0, whose schema is version 3.

## Problem Statement

The schema `_rowvioli` has a version (`meta.schema_version`, 3 in 0.1.0), and the program refuses a target
with another one. So the first release that changes the schema strands every user: the only way on is to
drop `_rowvioli`, which loses every table's state (`loaded_at`, attempts, the runs) and makes every table
due at once. That blocks every change that touches the schema, small ones included: a view over dead runs
(open points, "Left open"), a column for reading from a timestamp on, a worker that serves some sources.

## Solution

One sentence: **`rowvioli init` brings the schema to the version of the program that runs it, in one
transaction, and says what it did.** A command that creates the schema when it is missing already exists and
already needs the rights; migrating is the same act on an older target. No new command.

- **Tables are migrated, views are replaced.** The schema has three tables and `meta`, and views over them.
  A step from version n to n+1 is one SQL script that changes tables. The views (`status`) hold no state:
  they are dropped and created from the program's own definition at the end of every `init`, so most changes
  (a new column in the status view) need no step at all.
- **Steps are files, one per version**, `sql/migrate/4.sql` brings 3 to 4, and run in order from the
  target's version to the program's. All of them and the views in one transaction: it works or nothing changed.
- **Every other command refuses as today**, and now names the way on: `the target has schema version 3,
  this program works with version 4: run rowvioli init` (and `apply --init` does it on the way).
- **Never down.** A program older than the target refuses and says which version the target needs.
- **3 is the first version there is.** Targets of versions 1 and 2 existed only before the release.

## What a deployment looks like

1. Install the new program where `apply` runs. `rowvioli apply --init` migrates and applies.
2. Workers of the old version refuse the target at their next connect and stop (their service restarts them
   into the same refusal until they are updated). Runs they have in flight finish or fail as a run does.
3. Install the new program on the workers; they start.

Between 1 and 3 nothing loads. Tables get older, nothing is lost, and the first run afterwards catches up.

## Testing Decisions

The existing seam. A test builds a target with the schema of 0.1.0 (the released `schema.sql` kept as a
fixture under `tests/`, never edited), fills it through the old statements, runs `init` of the current
program, and asserts what a person sees: `status` before and after show the same tables, ages and reasons;
a run loads; `init` twice changes nothing. One such fixture per released schema version, forever.

## Who implements

Opus for the first step and the mechanism (what locks a migration takes while workers of the old version are
connected has to be found out); Sonnet for each later step, which is then one file and one fixture.

## Questions for the owner

1. **Is `init` the right place, or should it be said aloud** (`rowvioli init --migrate`)? Recommended: plain
   `init`. It is idempotent already, it needs the rights already, and a flag would be a second way to say
   the same thing. The price: an `init` run by habit on a production target changes it. It prints what it did.
2. **May workers of the old version keep running against a migrated target** when the step only adds
   (a new nullable column, a new view)? Recommended: no, one rule: the version is equal or the program
   refuses. Two kinds of steps would be the pile of rules this project avoids. The price is the gap in
   "What a deployment looks like".
3. **Should a worker wait instead of exit** when it meets a newer target, so that a service without restart
   policy survives the gap? Recommended: exit with the message. Waiting hides that the worker is outdated.
4. **Is "never down" acceptable**, i.e. a failed release is rolled forward, not back? Recommended: yes; a
   backup of `_rowvioli` (three small tables) before `init` is the way back, and the README says so.
5. **Which change comes first?** The mechanism is worth building only together with its first real step.
   Candidates from the open points: the view over dead runs (a view only, so it would exercise "views are
   replaced" but no table step), or reading from a timestamp on (a column in `tables`).

## Out of Scope

Migrating the mirrors, change logs or history views (they are the user's tables and have no version);
renaming `_rowvioli`; anything for versions 1 and 2.
