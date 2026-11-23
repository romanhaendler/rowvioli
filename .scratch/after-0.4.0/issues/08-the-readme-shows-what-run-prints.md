# 08: The README shows what `run` prints, and says what `+3 ~0 -0` means

**Status:** resolved

**Model:** Sonnet

From `.scratch/shakedown/sixth-run.md` (P1). Confirmed in the source by the coordinating session.

The block "What you see" in `README.md` shows a `✔ … ok` line per `run` but not the `▶ … started … run N` line that `run` prints before it. Nothing in the README says that `+3 ~0 -0` is inserted, updated, deleted; only `docs/operation.md` does.

- Make the block exactly what the commands above it print (run them against a throwaway target if that is cheap, else generate the lines from the code as the other examples were).
- One sentence under the block for the marks and the three counts, with the link to `docs/operation.md`. The same half-sentence where `docs/commands.md` and `docs/loading.md` show such a line.

## Comments

- Resolved. The block is what `run` printed against a throwaway target (`▶` and `✔` lines, stderr), times shortened as before. `docs/commands.md` and `docs/loading.md` show no such line, so they got no sentence.
