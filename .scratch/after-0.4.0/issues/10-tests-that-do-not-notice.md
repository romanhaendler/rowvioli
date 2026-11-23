# 10: Four mutants in the lines of 0.4.0 that no test notices

**Status:** ready-for-agent

**Model:** Sonnet

From `.scratch/shakedown/sixth-run.md` (P24, mutation run on `src/rowvioli/work.py`).

- `plain()`: the edges of the ranges (0x00, 0x1f, 0x7f, 0x9f, and 0x20, 0x7e, 0xa0 staying) are not tested.
- The `⚠` line may be red instead of yellow.
- The target table may be padded to 20 instead of 28.
- `sys.stderr.flush()` in `out()` can be deleted: find out whether it is needed (stderr to a file or a pipe is block-buffered in Python only if it is not a terminal? check what Python does) and either remove it or add the test that needs it.

One assertion or small test each; each must fail on its mutant.
