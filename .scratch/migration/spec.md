# Migration: `init` brings the bookkeeping schema to the program's version

Status: needs-triage (the owner answered the five questions on 2026-11-18, see the end; not yet cut into tickets)

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

## Decided by the owner, 2026-11-18

1. **Plain `init` migrates.** No flag. It prints what it did.
2. **One rule for versions**: the program's version equals the target's or the program refuses, also when a
   step only adds something.
3. **An outdated worker exits with the message.** It does not wait.
4. **Never down.** A failed release is rolled forward; a backup of `_rowvioli` before `init` is the way back,
   and the README says so.
5. **The first step is reading only rows from a timestamp on** (the most frequent gap in the shakedown of
   2026-11-18: P16, P22), built together with the mechanism.

Until the mechanism exists the project is in version 0 and the schema may change without a step (owner,
same day): a release that changes it says so in the changelog, and the target is initialised anew.

## Out of Scope

Migrating the mirrors, change logs or history views (they are the user's tables and have no version);
renaming `_rowvioli`; anything for versions 1 and 2.
