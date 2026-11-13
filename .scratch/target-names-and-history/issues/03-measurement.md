# 03: The measurement on a long history

**Blocked by:** 02

**Status:** ready-for-agent

**Model:** Sonnet

Spec: `.scratch/target-names-and-history/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Tests: the existing seam (`tests/conftest.py`), real processes against PostgreSQL in Docker, no import of the program. Disk: check `df -h .` and `docker system df` before and after; remove the containers and volumes your tests created. Prior art: `bench/` and the earlier sections of `docs/measurements.md`.

## What to build

Spec story 35: a bench script next to the existing ones and section 13 of `docs/measurements.md`. Measured on a long change log: the whole view, the view at one moment, the view for one key, and the same moment written directly against the log; each also with an index a person might create, so that 04 can say whether the README names one.

Only `bench/` and `docs/measurements.md` are touched. The section ends with a plain recommendation: name an index or not, name a faster query or not (with its SQL).

## Acceptance criteria

- [ ] Section 13 holds numbers that were really measured, with row counts and the set-up, in the form of the earlier sections.
- [ ] The measurement's volume is removed afterwards.
