# Load times: a table is due at fixed times of day

Status: ready-for-agent

## Problem Statement

A table can only say how old its mirror may get (`max_age`). It cannot say "load me at 14:00". `docs/decisions.md` names this as the price of decision 20 ("Load at six" cannot be said), and `docs/open-points.md` lists it as a known limit ("No fixed times").

The owner needs it: a table has to be loaded at a fixed time of day, for example every day at 14:00, whatever its maximum age is. Two things make `max_age` alone not enough:

- A daily table is due one maximum age after it was last loaded, so its time of day wanders. It never settles on 14:00.
- The only way to pin a time today is a cron outside rowvioli that sets `requested_at`. The time is then not in the definition, passes no review, and a cron that did not run is never caught up.

## Solution

A table gets **load times**: a list of times of day in the definition.

```toml
[erp]
max_age  = "1d"
timezone = "Europe/Berlin"

[erp.tables]
"dbo.Orders" = { key = ["order_no"], at = ["06:00", "14:00"] }
```

A load time is a request that the clock makes. The rule is one sentence, and it is the rule a request already follows:

> A table is due at its next load time after the last run began.

Everything else follows from the facts already stored, as it does for a request. Nothing new is stored about what happened, nothing is reset, no process knows about a schedule. `max_age` stays as it is, and whichever comes first makes the table due.

## User Stories

### Defining load times

1. As a definition author, I want to give a table a list of times of day with `at`, so that it is loaded at those times whatever its maximum age is.
2. As a definition author, I want to give several load times, so that a table can be loaded for example at 06:00 and at 14:00.
3. As a definition author, I want to write a single load time as a list with one entry, so that there is one way to write it.
4. As a definition author, I want to set `at` for a source and override it for a single table, so that it behaves like `max_age` and the other settings.
5. As a definition author, I want a table's `at` to replace the source's list instead of adding to it, so that I can read a table's load times from one line.
6. As a definition author, I want `at = []` on a table to switch off the source's load times for that table, so that one table can stay with its maximum age alone.
7. As a definition author, I want to name the time zone the load times are meant in with `timezone`, for a source or a table, so that 14:00 means 14:00 where the business is.
8. As a definition author, I want `apply --check` to refuse load times without a time zone, so that nobody finds out in production that 14:00 was UTC.
9. As a definition author, I want `apply --check` to refuse a time that is not `HH:MM` between `00:00` and `23:59`, and a time zone that does not exist, with a message that names the file, the source and the table, so that a typing mistake is rejected before the merge.
10. As a definition author, I want to keep writing `max_age`, so that the table still has an answer when no load time is near: for the pause after a failure, for the order among due tables, and for a mirror that would otherwise get older than I allow.

### Being due

11. As an operator, I want a table to be due at its next load time after the last run began, so that it is loaded at 14:00 even though it was loaded an hour before.
12. As an operator, I want the table to be due at whichever comes first, its next load time or its maximum age, so that a load time never makes a mirror older than `max_age` allows.
13. As an operator, I want a daily load to stay at 14:00 day after day, so that its time of day does not wander with the duration of the runs.
14. As an operator, I want a load time that passed while no worker was running to be caught up as soon as a worker runs, so that a missed 14:00 is not lost.
15. As an operator, I want several load times that passed while no worker was running to give one run, so that a restart after a night does not load a table twice in a row.
16. As an operator, I want a load time that passes while the table is loading to give one more run afterwards, so that the mirror is not older than the load time says. This is what a request during a run does.
17. As an operator, I want a load time to make a table due even while it pauses after a failed run, so that a table that failed at 06:00 is tried again at 14:00 at the latest. This is what a request during a pause does.
18. As an operator, I want a table whose run at a load time fails to be retried after the usual pause, so that a load time adds no second retry rule.
19. As an operator, I want a table that was never attempted to be due at once, with or without load times, so that a new table does not wait for 14:00.
20. As an operator, I want a request to work as before on a table with load times, so that "load now" stays one statement.
21. As an operator, I want changed load times or a changed time zone to take effect with the next query after `apply`, without a run, so that it behaves like a changed `max_age`.
22. As an operator, I want `apply` to leave what the workers experienced untouched when load times change, so that a deployment still triggers no load by itself beyond what the new times say.
23. As an operator, I want the day the clocks change to do no harm: a load time in the skipped hour is due once at the moved time, a load time in the repeated hour gives one run, so that summer time needs no attention.
24. As an operator, I want due tables to be taken in the same order as before, the most overdue measured in maximum ages first, so that load times add no rule of precedence.

### Seeing it

25. As an operator, I want `due_at` in the status view to show the next load time when that comes before the maximum age, so that I can see when a table will be loaded next.
26. As an operator, I want to read a table's load times and time zone from `_rowvioli.tables`, so that I can answer why a table was due without opening the definition.
27. As an operator, I want every command to refuse a target that was initialised before load times existed, naming both schema versions, so that I get a clear message instead of an SQL error.

### Reading the documents

28. As a reader of the repo, I want the README, the glossary and the decisions to say the same thing about time, so that "you state the freshness, not the time" is not contradicted two sections later.
29. As a reader of the decisions, I want to see why fixed times were added after decision 20 named them as a price, and what was rejected, so that I do not propose cron syntax next.

## Implementation Decisions

### The rule

- **One more term in the due formula.** The view computes the *next load time*: the earliest point in time that is later than `attempted_at` and falls on one of the table's times of day in the table's time zone. `due_at` is the earlier of that and what the formula gives today. A table without load times has no next load time and behaves exactly as today.
- **`attempted_at` is the anchor**, as for a request. It is the start of the last run, set when the table is claimed. A load time after it is unserved, a load time before it is served. This is why nothing is reset and no flag exists.
- **A load time ranks like a request, not like the maximum age.** It applies in every state: after a success, during a pause, and after a run that started before it. A never-attempted table stays due at once.
- **Catching up needs no code.** The next load time after the last run began is in the past when workers were away, so the table is due. After that run `attempted_at` is later than all missed times, so they count once.
- **The order among due tables is unchanged:** time since `due_at` measured in maximum ages.
- **The pause is unchanged:** one minute, doubling, never longer than `max_age`.
- **Clock changes are left to Postgres.** A local time is turned into a point in time by Postgres' own conversion for the named zone. No code of rowvioli handles summer time.

### The definition

- **`at`** is a list of strings `HH:MM`, 24 hours, `00:00` to `23:59`. A plain string is refused: one way to write it. An empty list means no load times. Duplicates are harmless and not an error.
- **`timezone`** is an IANA name such as `Europe/Berlin`. A table with a non-empty `at` needs one, from the table or the source. There is no default, not UTC and not the server's zone. A `timezone` without any `at` is allowed.
- Both are table settings in the sense of the existing ones: settable for a source, overridable for a table, and stored on the table's row with the source's filled in by `apply`.
- **Weekdays, dates, intervals and patterns are not expressible.** "Every full hour" is `max_age = "1h"`.
- `max_age` stays required at source level.

### Checking

- `apply --check` checks the format of every time and that the time zone exists, without a target.
- `apply` against the target fails and changes nothing if the target's Postgres does not know a time zone. The view computes with Postgres' zones, and an unknown zone on one row would fail the view for every table.
- Known gap, accepted: whoever writes `_rowvioli.tables` by hand with an unknown zone breaks the status view. Write access to the definition columns is already limited to the role that runs `apply` (decision 22).

### Schema

- `_rowvioli.tables` gets two definition columns: the load times as an array of times of day, and the time zone as text. Both may be empty.
- The view `_rowvioli.status` gets the term above. Its columns do not change.
- **The schema version becomes 2.** Version 0.1 is not released, so there is no migration: a target of version 1 is refused with the existing message and initialised anew. The versioned schema is edited in place.
- `apply` writes the two columns as it writes the other definition columns, and nothing else.

### The decision is adapted

This spec changes a stated decision, and the change is part of the work. `docs/decisions.md` gets a new decision at the end of the numbered ones, and the places that say the opposite are corrected.

**New decision 36: a load time is a request the clock makes.**

- *Decision.* A table may name times of day (`at`) in a time zone (`timezone`). It is due at its next load time after the last run began, or by its maximum age, whichever comes first. The times are part of the definition; the due time is still computed from stored facts on every query.
- *Why.* The owner needs tables that are loaded at a fixed time. A daily maximum age wanders, and a cron that sets `requested_at` keeps the time outside the definition and does not catch up. The rule is the request's rule with the clock as the one who asks, so it brings no new concept: no schedule, no stored next time, nothing to reset, no process that knows about time beyond the view.
- *Price.* The sentence "you state the freshness, not the time" is no longer the whole truth: you may state both. The target needs to know time zones, and a wrong zone on a row breaks the view. Load on the source arrives at the named minute again for the tables that use it, which decision 20 had spread out; `parallel` and `max_running` still bound it.
- *Rejected.*
  - *A cron outside that sets `requested_at`.* Works today and stays the right answer for "load when the source's batch is done". For a time of day it keeps the time out of the definition and loses a missed run.
  - *Aligning `max_age` to a grid* ("daily, anchored at 14:00"). A second meaning for the one setting everybody knows, and it cannot say 06:00 and 14:00.
  - *Cron syntax or weekdays.* A schedule language where a list of times answers what was asked.
  - *A default time zone.* 14:00 that silently means UTC is a mistake found in production.

**Corrections that follow from it:**

- Decision 20, price: "Load at six" cannot be said → could not be said until decision 36. The decision itself stands.
- Decision 23: the stored columns it lists now include the load times and the time zone as definition; the sentence that the due time is computed from facts stands.
- The table "Changes of the second round" and the section "Not examined" are left as history.
- `docs/open-points.md`, known limits: "No fixed times" is removed. "A load after an event needs a request from outside" stays, as its own point.
- `GLOSSARY.md`: a new term **Load time** (`at`: a time of day at which a table is due, in the table's time zone); **Due** names the next load time after the last run began as one more case; **Maximum age** is unchanged.
- `README.md`: the sentence "You state the freshness, not the time" is reworded so that it is still the lead idea and load times are the addition; the settings table gets `at` and `timezone`; the facts table and the due formula get the new term; the paragraph on retry keeps its nightly example; the state diagram's edges to `due` name the load time next to the request; the table of situations gets the rows for a missed load time and a load time during a run; the overview of what can be done from where gets "load at a fixed time".

## Testing Decisions

- **The existing seam, nothing new.** Tests start the commands as real processes against real PostgreSQL in Docker and look only at what a user sees (`.scratch/v0.1/spec.md`, "Testing Decisions"). No test imports a module of the program.
- **A good test** states one sentence of this spec and would pass if the view were rewritten. It never matches the view's SQL text.
- **No simulated clock.** The rule only compares points in time, so tests write facts with fixed dates in the past into `_rowvioli.tables` and read `due_at` from the status view. This is how the status view is tested today (`tests/test_status.py`), and most of the feature is tested there.
- **The clock change is tested with fixed dates** in `Europe/Berlin`: the last Sunday of March for the skipped hour, the last Sunday of October for the repeated hour.

What is tested:

1. A table loaded successfully before a load time is due at that load time, not one maximum age after loading.
2. With a maximum age that ends before the next load time, the table is due by its maximum age.
3. With several load times, the table is due at the earliest one after the last run began; a later day's first time is found across midnight.
4. A load time before the last run began does not make the table due.
5. Several load times after the last run began give a `due_at` in the past and, after one run, a `due_at` in the future.
6. A failed table in its pause is due at a load time that comes before the end of the pause; without one, the pause holds as before.
7. A never-attempted table with load times is due now.
8. A request after the last run began still wins over a later load time.
9. The same local time in two time zones gives two different points in time.
10. A load time in the skipped hour of the spring change is due once on that day; a load time in the repeated hour of the autumn change gives one `due_at`.
11. A table without load times has the same `due_at` as before, in every status (the existing status tests stay green unchanged).
12. `apply` stores a source's `at` and `timezone` on its tables, a table's own values instead where given, and `at = []` switches the source's off (prior art: `tests/test_apply.py`).
13. `apply --check` fails each of: `at` as a plain string, a time that is not `HH:MM`, `24:00`, a non-empty `at` without `timezone`, an unknown `timezone`. Each message names the setting (prior art: the parametrised invalid definitions in `tests/test_apply.py`).
14. Changed load times change `due_at` after `apply` without a run, and `apply` leaves `loaded_at`, `attempted_at`, `attempts` and `requested_at` as they were.
15. One run through the real loop: a table that is fresh by its maximum age but has a load time after its last run is loaded by `rowvioli run`, and is not loaded a second time by the next `run` (prior art: `tests/test_run.py`).
16. A target of schema version 1 is refused, naming both versions (existing test, new number).

Disk space: the harness's rule stands. Containers and volumes are removed after the session.

## Out of Scope

- Weekdays, dates, "every n hours", cron syntax, holidays.
- A load after an event in the source. That stays a request from outside (`requested_at`).
- A default time zone, a time zone for the whole target, or reading the server's zone.
- Making `max_age` optional for tables with load times.
- New columns in the status view. `due_at` shows the effect; the settings are in `_rowvioli.tables`.
- A migration from schema version 1.
- A window ("not before 14:00, not after 15:00") or a deadline ("fresh by 14:00").
- Spreading tables that share a load time over a few minutes. `parallel` and `max_running` bound the load.

## Further Notes

- The owner asked for this on 2026-11-12 and chose it over the request from outside after a brainstorm: first one time, then a list of times. The owner did not state why 14:00. If the reason is an event in the source, the request is the better tool, and the README should say so next to `at`.
- Open for the owner, decided here by assumption: `timezone` per source or table with no default; `at` settable at source level; schema version 2 without migration.
- The owner's rule for this repo applies: one carrying idea, no pile of rules. The measure for the implementation is that the README needs one sentence for load times and can point to the request for every consequence.
- A table that takes longer to load than the gap between two of its load times loads without a break. This is the existing limit for `max_age` (`docs/open-points.md`) and gets no new rule.
