# 03: `apply` refuses control characters in the names of the definition

**Status:** resolved

**Model:** Sonnet

From `.scratch/shakedown/fifth-run.md` (P18). The root of the escape-code findings: 0.4.0 only writes such characters as `?` in the lines.

## What to build

`apply` (and `apply --check`, `list`) accept `target_table = "a\u001b[2J\nB"`. A name with a control character can clear a terminal, forge a log line and is nothing a person can type in SQL.

- The names the definition gives (source name, source table, `target_schema`, `target_table`, key columns) may hold no control character (C0, DEL, C1, U+2028, U+2029). `apply` fails and names the source file, the setting and the name with the character shown as an escape (`\x1b`), next to the other name rules of decision 39.
- Nothing already in a target is touched: a name applied by an older version keeps loading, and the lines still write it with `?`.
- `docs/definition.md` names the rule where it names the others; `docs/decisions.md` gets a sentence at decision 39 or a short new decision, following how decisions were changed before.

## Acceptance criteria

- [ ] A test per setting: `apply` exits non-zero and the message names file, setting and the escaped name.
- [ ] `apply --check` and `list` fail the same way.

## Comments

`definition.clean` checks the five kinds of name while reading; decision 39 is extended in place with one sentence, as earlier small additions were.
