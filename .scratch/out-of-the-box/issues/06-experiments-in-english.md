# 06: The experiments in English

**Blocked by:** none

**Status:** resolved

**Model:** Sonnet

The owner's rule: every name and text in the repo is English. The only German left is `experiments/`: the
file names (`01_veroeffentlichen.sql` ...), identifiers (`lauf`, `auftrag`, `quelle_id`, `tabelle_id`,
`versuch`), status values (`wartet`, `läuft`, `gestorben`), comments and output, and the schema `_etl`.

## What to build

- Rename the files (`git mv`) and translate identifiers, status values, comments and output, using the words of
  `GLOSSARY.md` and the table in `experiments/README.md` (`_etl` becomes `_rowvioli`). Logic, numbers and
  statement order stay byte for byte otherwise.
- `experiments/README.md`: drop the translation table and the sentence about German; fix the commands.
- Every reference to the old names elsewhere (`docs/measurements.md`, `docs/decisions.md`, `.scratch/`, README).
- German words that are test data stay (`Köln`, `Kunden_Ä`, `tökén`: they test umlauts).

## Acceptance criteria

- [ ] Each script runs once as the README says, with a small `n` where it takes one, and ends without an error; 08 as far as its needs are met. The container is removed afterwards with `docker rm -fv`.
- [ ] `git grep -I -i -E "quelle|tabelle|lauf|vergabe|wartet|gestorben|_etl"` finds nothing but test data.
- [ ] The measurements' numbers in `docs/measurements.md` are untouched.

## Comments

Resolved. Files (`git mv`): `01_veroeffentlichen.sql` to `01_publish.sql`, `02_breite_tabelle.sql` to `02_wide_table.sql`,
`03_unterschiede_vorab.sql` to `03_diff_upfront.sql`, `04_harter_abbruch.sh` to `04_hard_kill.sh`, `05_vergabe.sql/.sh` to
`05_claim.sql/.sh`, `07_geheimnisse.py` to `07_secrets.py`, `08_treiber.py` to `08_drivers.py`. Identifiers: `_etl` to
`_rowvioli`, `lauf` to `run`, `auftrag` to `order_id`, `quelle_id` to `source_id`, `tabelle_id` to `table_id`, `versuch` to
`attempt`, `zieltabelle` to `target_table`, `ende` to `finished`, `grund` to `reason`, `opfer` to `victim`; the 08 function
`lauf` to `one_run`. Status values: `wartet`, `läuft`, `gestorben` to `waiting`, `running`, `dead`; the reason
`Worker ausgefallen` to `worker lost`. Comments, `\echo` and output translated. Also fixed: `README.md`,
`docs/measurements.md` (names only, no number touched), `experiments/README.md` (table and German sentence dropped).
`docs/decisions.md` line 672 keeps `_etl`: it is the old-to-new row of the rename table.

Runs (Postgres 16 container `rowvioli-exp-06`, removed with `docker rm -fv`; one extra `rowvioli-exp-06b` for 08, also removed):
01, 03, 06 with `n=10000`: end without error (06 ends with the expected `integer = text` error). 02 at its fixed size:
ends without error. 04: lock gone at once, held after 2 s, gone after 17 s, gone after 4 s with the check interval.
05: erp 4 / crm 2, no sample over the limit, one dead run retried with attempt 2. 07: all six checks pass (check 3 reports a
`TypeError`, not a decrypt error; logic untouched). 08 with 10000 rows: all ok except the streaming check, which needs more
than one 10,000-row chunk; with 300000 rows it passes. Each of 01, 02, 03, 06 ran in a database of its own inside one container.
