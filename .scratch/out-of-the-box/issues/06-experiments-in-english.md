# 06: The experiments in English

**Blocked by:** none

**Status:** ready-for-agent

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
