# 10: After the review and the personas: the right key, slips named, a renamed table is new

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Sonnet

From the review of 2026-11-18 (findings 2 to 7, 9) and the personas P1 and P4 on the wheel.

## What to build

**The key (P1, review 4).** The message of ticket 01 sends a second machine to `rowvioli key new`, which
creates a key that cannot decrypt anything; every table then fails with `holds no private key <id>`.
- A missing key file says: copy `worker.key` from where `rowvioli key new` was run; only for a new target
  does `rowvioli key new` create it.
- `holds no private key <id>` says that this is not the key the definition was applied with, and names both
  ways out: the `worker.key` that belongs to the `worker.pub` next to the definition, or `apply` again with
  this key's `worker.pub`.
- The start check opens the file instead of testing that it exists: a directory or an unreadable file stops
  `run` and `work` at the start, with the system's reason.

**Slips (review 2, P1).**
- `edits` counts two neighbouring letters swapped as one edit (`fiel`, `rset`, `max_aeg`).
- A setting of three letters or fewer that is one edit from `key`, `log` or `at` fails like the longer ones
  (`kye`, `ky`, `kee`). `sep` stays possible: it is two edits from `key`.
- `type`: one edit from any of the four built-in names, and `postgresql`, fail with "did you mean". The
  message does not claim that the type "is not a connector". A type that is installed where `apply` runs
  always passes, so a connector of one's own named `jdbc` has a way through; the message says so.
  `postgis` (two edits) passes.

**A renamed table is new (review 3).** Where `apply` resets `attempted_at` for a changed target name it also
resets `attempts`, `reason` and `loaded_at`: status shows no age and no old reason for a mirror that does not
exist, and a first failure pauses one minute. `requested_at` stays. The comment at the top of `apply.sql` says so.

**Messages.**
- `rows` of the rest connector that is not a non-empty string: `<table>: the option rows must be a field name`.
- `apply` without a directory where `sources` does not exist: names the directory it looked in and that
  `rowvioli apply <directory>` takes another.
- `run <name>` where `<name>` is no source: says that the first name is a source, and suggests the source
  when exactly one enabled table ends in the name.
- A target address with more than one `@` after the scheme fails before connecting: a password with `@`,
  `/` or `:` must be percent-encoded. No part of the address in the message.

**Documents** (README, `docs/decisions.md`, `docs/open-points.md`, `CHANGELOG.md`).
- The key on a second machine, in the README's start (half a line) and "Where the keys live".
- Decision 45 as built now; decision 46 with the three more columns; the preamble of `docs/decisions.md`
  names 44 to 46; the sentence near line 287 and decision 22 agree with 46; decision 2's rejected "Hash per
  row in the worker" loses "Faster for large tables", which rests on nothing since ticket 07.
- `file`: a table by pattern mirrors what the directory holds now, so files moved away take their rows with
  them and meet the limit on deletions (P4). JSON numbers are not "as written": `10.50` arrives as `10.5`,
  `1E2` as `100.0`, and a change from `1.0` to `1` is no change (jsonb equality). A string with `\u0000` fails
  without naming the column. Known limits.
- History: it begins with the first load, said where `__history` is introduced (P4).
- Open points: the three-letter limit goes or is restated as built.

## Acceptance criteria

- [ ] In a second directory without `worker.key`, `run` names copying the key; after a wrong `key new` there, the reason names both ways out.
- [ ] `fiel`, `rset`, `postgresql`, `kye`, `ky` fail `apply --check` with the right suggestion; `sep`, `postgis`, `weather` and an installed custom type one letter from `odbc` pass.
- [ ] A failed table with attempts, renamed and applied: status shows no age, no reason, due now; a failure then waits one minute.
- [ ] The whole suite is green.

## Comments
