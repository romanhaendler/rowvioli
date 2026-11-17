# 14: A numeric keeps its precision and scale

**Blocked by:** none

**Status:** resolved

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

- [x] A source column `numeric(12,2)` with `137.00` arrives as `numeric(12,2)` `137.00` in a new mirror, or the comment says with evidence why it cannot.
- [x] An existing target table with `numeric(10,2)` columns and a view on it loads on the first run and equals the source.
- [x] A second unchanged run reports no change; a change of scale in the source (`numeric(12,2)` to `numeric(12,4)`) is caught or carried, and the comment says which and why.
- [x] A mirror made by 0.1.0 (`numeric` where the source has `numeric(p,s)`) keeps loading.
- [x] The whole suite is green.

## Comments

2026-11-17, Opus. Changed: `load.py` (two hunks: `stage()` creates the staging table before filling it, a new
`fit()` called from `load()`), `connectors/postgres.py` (the sign of the scale), tests, documents. Decision 49
(numbered so because another branch may add 47 and 48).

### What was measured

adbc-driver-postgresql 1.13.0, pyarrow 26.0.1, DuckDB 2.0.0, `postgres:16-alpine`; psqlODBC in
`tests/odbc/run.sh`'s container. "Before" is 0.1.0 and part-2, for the staging table and a new mirror.

| Source type, value | Connector delivers | Before | Now |
|---|---|---|---|
| `numeric(12,2)` `137.00` | `decimal128(12,2)` | `numeric` `137` | `numeric(12,2)` `137.00` |
| `numeric(38,10)` `1.5` | `decimal128(38,10)` | `numeric` `1.5` | `numeric(38,10)` `1.5000000000` |
| `numeric(50,5)` `123.45` | `decimal256(50,5)` | `numeric` `123.45` | the same |
| `numeric` `1.10` | `decimal256(76,38)` | `numeric` `1.1` | the same |
| `numeric(5,0)` `5` | `decimal128(5,0)` | `numeric` `5` | `numeric(5,0)` `5` |
| `numeric(5,-2)` `12345` (stored `12300`) | `decimal128(5,2046)`, now `(5,-2)` | the run failed: `Rescaling Decimal value would cause data loss` | `numeric(5,-2)` `12300` |
| NULL in each | null | NULL | NULL |
| `NaN` in `numeric` | | fails: `The string 'nan' is not a valid decimal256 number` | the same |
| `file`, `decimal(10,2)` through `columns` | `decimal128(10,2)` | `numeric` | `numeric(10,2)` |
| `odbc` (psqlODBC), `numeric(12,2)`, `numeric(38,10)` | `decimal128(p,s)` | `numeric` | `numeric(p,s)` |
| `odbc`, `numeric(50,5)` | text | `text` | the same |
| `odbc`, `numeric` `0.1234567891` | `decimal128(28,6)` | `numeric` `0.123456` | `numeric(28,6)` `0.123456` |
| `rest` | has no decimal type | | unchanged |
| `varchar(20)` | string | `text` | the same |

- **The driver creates every Arrow decimal as `numeric`** and writes a value without its trailing zeros (`137.00`
  as `137`, `2.50` as `2.5`, in every precision). Postgres applies the column's scale on the way in, so a
  `numeric(12,2)` column gives `137.00` back.
- **The driver appends into a TEMP table it did not create** (`mode="append", temporary=True`), in that table's
  types. Creating the staging table without rows, altering its decimal columns and appending cost 0.03 s; altering
  the filled table instead cost 0.6 to 1.0 s per 10⁶ rows (six columns, one decimal; the fill itself 3 to 4 s).
- **`schema.empty_table()` fails** for a list of an extension type (`money[]`, read as a list of PostgreSQL's opaque
  numeric): `ArrowNotImplementedError: extension`. A reader without batches works.
- **Postgres 15 allows a negative scale**; the typmod's scale is 11 bits with a sign, which the connector read as
  2046. Fixed. Arrow and the driver carry `decimal128(5,-2)` and `decimal128(3,5)` (scale above precision).

### Design

- **Item 1, built.** The staging table is created from the connector's schema without rows; each `decimal128(p,s)`
  becomes `numeric(p,s)`; then the rows are appended. It holds for every connector, since a decimal128 always has
  its precision and scale. `decimal256` stays `numeric`: the `postgres` connector delivers an unconstrained
  `numeric` as `decimal256(76,38)`, and Arrow has no "unconstrained", so a `numeric(p,s)` beyond 38 digits gets
  `numeric` in a new mirror. Naming the unconstrained case in field metadata would have been a second agreement
  between connector and core.
- **Item 2, built, and it carries existing mirrors.** `fit()`: a staged column whose type differs from the mirror's
  or the change log's only in its modifier (Postgres says so: `$1::regtype = $2::regtype`) takes the mirror's type,
  when `col::<target type> IS DISTINCT FROM col` finds no value; otherwise the run fails with `column price holds a
  value that its type numeric(10,2) in raw_erp.prices does not hold (1.005)`. A value too large for the precision
  raises in the cast; its message (`numeric field overflow`) stands in the parenthesis. After `fit()` the staged
  types equal the mirror's, so the schema check, the diff, publishing and the change log are untouched, and the
  comparison happens in the target type: a second unchanged run reports nothing (tested for new mirrors, for
  `numeric(10,2)` taking an unconstrained `numeric`, and for a 0.1.0 mirror). A real change of type (`numeric` to
  `integer`, `json` to `jsonb`) is a different `regtype` and fails as before.
- **A change of scale in the source** (`numeric(12,2)` to `numeric(12,4)`) **is neither carried nor caught by its
  type: it is caught by its values.** The mirror keeps `numeric(12,2)` and loads while every value fits; the first
  `1.2345` fails and names column, type, table and value. The README gives the three statements (drop the history
  view, alter mirror and log; the next run creates the view again), tested. Carrying it by `ALTER` was rejected:
  a view on the mirror blocks it (P16), and it would change a consumer's type unasked.
- **The change log is checked too**: a log narrower than its mirror (half the recipe) fails instead of rounding.
- **Item 3, not changed.** `varchar(n)` arrives as `text`, and to Postgres `text` and `varchar` are two types,
  not one type with a modifier, so it does not fall out of `fit()`; making it would be a second rule (binary
  coercible casts). An existing `varchar(n)` target column still fails as a change of type.

### Existing mirrors

A mirror made by 0.1.0 has `numeric` where the source has `numeric(12,2)`. Its first run with the new program
stages `numeric(12,2)`, `fit()` takes the mirror's `numeric` (every value fits), and the run loads, reporting
nothing for unchanged rows (`137` and `137.00` are equal). Nothing to do; the mirror keeps `numeric` until a person
alters it with the README's statements. Test: the mirror and the log altered back to `numeric`, the values
trimmed, the history view dropped, then two runs.

### Left out, and found

- A new mirror of a `numeric(p,s)` beyond 38 digits gets `numeric`.
- **psqlODBC cuts an unconstrained `numeric` to six decimals** (`0.1234567891` arrives as `0.123456`): it describes
  the column as `numeric(28,6)`, and arrow-odbc reads it so. Before this change too, unseen behind `numeric`; now
  the mirror's type shows it. Not fixed here: it is the ODBC driver's description; a ticket of its own if wanted.
- `numeric[]` arrives as `text[]` (the driver's list of opaque), as before.
- A value too large for the precision is named by Postgres's message, not by the value.
- SQL Server and Informix through ODBC not tried.
