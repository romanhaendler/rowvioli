# 14: A numeric keeps its precision and scale

**Blocked by:** none

**Status:** ready-for-agent

**Model:** Opus

From the shakedown of 2026-11-18. P16 (a team moving existing mirrors to rowvioli): four of eight existing
target tables failed their first run with `column price has changed its type from numeric(10,2) to
numeric`, a change nobody made; the way out, `ALTER TABLE ... TYPE numeric`, is blocked when a view reads
the table. P3: a source value `137.00` in a `numeric(12,2)` column stands in the mirror as `137`. Decision 28
and the README ("Types", "Decimals from Postgres") describe the cause: the driver decides the types,
`numeric(p,s)` arrives as `numeric`.

The owner, 2026-11-18: the project is in version 0; anything may change if it is better afterwards.

## What to find out and build

What is better afterwards is for this ticket to find out by trying, in this order of worth:

1. **A new mirror of a Postgres source has `numeric(p,s)` where the source has it**, so that `137.00` stays
   `137.00` and a consumer's tools see the same type as in the source. Find out what the connector and the
   driver can carry (the connector converts to Arrow decimals today; an Arrow decimal has precision and
   scale), what the staging table and the mirror are created from, and what happens beyond 38 digits and with
   an unconstrained `numeric` (which must stay `numeric`).
2. **An existing target table whose column is `numeric(p,s)` is taken over** when the values fit, whatever
   the connector delivers, and fails with a reason a person can act on when they do not (a value with more
   digits than the column holds). The schema check must still catch a real change of type.
3. The same question for the other pair the README names, `varchar(n)` arriving as `text`: say what you
   found; change it only if it falls out of the same mechanism without a second rule.

The rule of the project decides between designs: a run is right or it fails and says why; the comparison
happens in the target type (so `137.00` and `137.0` must not count as a change on every run: check a second
unchanged run); the smallest mechanism that does it. If carrying precision and scale costs a second concept,
build only item 2 and record why.

Existing mirrors made by 0.1.0 have `numeric` columns where the source has `numeric(p,s)`: say what happens
to them on the first run with the new program (they must keep loading, or fail with the way out named), and
write that sentence for the changelog under "Changed".

Documents: README "Types" and the passage on taking over existing tables if it exists, decision 28 or a new
decision, `docs/open-points.md` (the limit "The driver decides the types"), `CHANGELOG.md`.

## Acceptance criteria

- [ ] A source column `numeric(12,2)` with `137.00` arrives as `numeric(12,2)` `137.00` in a new mirror, or the comment says with evidence why it cannot.
- [ ] An existing target table with `numeric(10,2)` columns and a view on it loads on the first run and equals the source.
- [ ] A second unchanged run reports no change; a change of scale in the source (`numeric(12,2)` to `numeric(12,4)`) is caught or carried, and the comment says which and why.
- [ ] A mirror made by 0.1.0 (`numeric` where the source has `numeric(p,s)`) keeps loading.
- [ ] The whole suite is green.

## Comments
