# 04: Documents and version

**Blocked by:** 01, 02, 03

**Status:** resolved

**Model:** Sonnet

Spec: `.scratch/connectors/spec.md`, stories 37, 38, 41 and "Version and documents". Read the comments of tickets 02 and 03 for what was built differently and for a type conversion.

## What to build

- The version becomes 0.2.0 (project file, lock). Nothing is tagged or published.
- README "Connectors": the table, the sentence about versions, the options of `odbc` and `rest` described once, the pointer to the custom connector for other paging, wrapped responses or headers; "Types" if ticket 03 needed a conversion; the installation line where it names extras. The paragraph "Licences" exists from ticket 01.
- `docs/package.md`: the state of 0.2 for connectors. `docs/open-points.md`: `odbc` and `rest` leave "Not built"; JSON files stay.
- Every sentence is checked against the program as built, not against the spec.

## Acceptance criteria

- [ ] No document says that `odbc` or `rest` is not built, and none names 0.1 as the current version.
- [ ] The tests pass.

## Comments

Resolved on branch `connectors`, from con-04 (f1e5035). Review fixes: 8ce4756.
