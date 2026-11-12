# 05: A guide: a connector that needs licensed software

**Blocked by:** 03

**Status:** ready-for-agent

**Model:** Opus

Spec: `.scratch/connectors/spec.md` (stories 2 to 4, 10, 37; decision 38 in `docs/decisions.md`; "Further Notes", last bullet). Material: the README section on custom connectors, `src/rowvioli/contract.py`, the shipped connectors, the test connector package under `tests/connector`, the comments of ticket 03.

## What to build

One document, `docs/connector-guide.md`, linked from the README where it speaks of custom connectors and from the paragraph "Licences". The reader has a source whose driver or SDK is under a vendor licence or GPL (SQL Server, Informix, Oracle, SAP) and wants a connector without putting the project or themselves in the wrong. The measure: they can follow it from an empty directory to a mirrored table without asking anyone.

- The one carrying sentence of decision 38 first, then what follows for this reader. No pile of rules.
- First question: is ODBC enough? Then no connector is written: install the vendor's driver yourself, `type = "odbc"`. What to check on an untested source (types, the driver quoting the connection string in errors), from ticket 03's comments.
- Otherwise a separate package, worked through as one complete small example that exists and runs: project file with the entry point, `read`, optionally `tables`, install next to rowvioli, a source definition, a run. Take the example from what the repo already has and tests (`tests/connector`); do not invent a second one.
- Where the licensed software lives: installed by the operator, never in the package, the repo or an image that is passed on; the package's own licence; code written from the vendor's public documentation, not ported.
- How to test such a connector: against the vendor's developer edition under terms the tester accepts themselves; where the acceptance is set and who sets it; what was read in Microsoft's terms and what could not be read in IBM's (spec "Further Notes"), stated as what the texts say, with "not legal advice" once.
- Secrets: connection values are scrubbed from reasons; what a connector must not print.
- Plain style of the README. Every command and every code line in the guide is run before it is written down.

## Acceptance criteria

- [ ] A test keeps the guide true where that is cheap: the example the guide shows is the code under `tests/connector` (or is checked against it), so it cannot rot.
- [ ] No vendor file, no logo, no copied vendor documentation.
- [ ] The existing tests pass.

## Comments
