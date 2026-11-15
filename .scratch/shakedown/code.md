# Shakedown 2026-11-15: code

Status: needs-triage (taken up in `spec.md`)

From P27 (the deleter): vulture finds nothing dead in `src` (1142 lines). The fat is in the docs.

## Findings

1. ✓ **[Dead] README "Web UI"** (README:902-920, about 19 lines) describes what is not built (open points:72),
   partly as fact ("Cancel a run").
2. **[Duplication] README "Measurements"** (README:922-937) repeats `docs/measurements.md`; two copies can drift.
3. **[Duplication] `docs/package.md`**: the repo tree and the "Name" checklist (about 50 lines) repeat the
   filesystem and open points. Keep "Dependencies": `tests/test_licences.py` reads it.
4. **[Duplication] `docs/connector-guide.md`'s opening** restates decision 38 and README "Licences" word for word.
5. ✓ **[Weak test] `apply --key` has no test and no user** (README:653 only). `list --definition` does have
   one: `examples/informix/compose.yaml:41` (P27 missed it). Either test `--key` or drop it; see also
   `first-use.md` 2.
6. ✓ **[Duplication] `test_rest.py:143-147` and `test_list.py:70-77`** assert the same line from `cli.py:101`.

Not recommended, listed for the owner: the mascot (decision 37) and `experiments/` (695 lines, the proof of
the measurements).

## What held up

No unused function or constant; one fail path in `load.py`; connectors 43 to 72 lines; almost every option tested.
