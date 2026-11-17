# Shakedown 2026-11-15

Status: resolved (taken up in `spec.md`)

The first run (procedure: `docs/agents/shakedown/`). Wheel 0.2.0, one wave of six Sonnet agents: H1 install
and target, H2 hostile source data, P1 Lena, P4 Jonas, P18 security, P27 the deleter. Not run: H4, P3, P16,
P20, P22, P23, P24. ✓ = reproduced on the wheel or confirmed in the source by the coordinating session;
the rest are leads.

| File | What |
|---|---|
| `security.md` | two leaks of a secret, a file outside its directory, TLS |
| `source-data.md` | types that arrive wrong or break the second run, REST shape changes, messages |
| `first-use.md` | the traps of a beginner and of a coding agent |
| `install-target.md` | pooler, rights, masking, extras |
| `code.md` | what could go |
| `wishes.md` | the wishes with their three proofs |

## The five that matter most

1. ✓ **A REST token can be sent to any host by whoever writes `_rowvioli.tables`** (`security.md` 1). Breaks a README promise.
2. ✓ **`json`/`jsonb` columns load once and fail on every later run** (`source-data.md` 1).
3. ✓ **`inet`, `xml`, ranges arrive as unreadable `bytea`, `money` as cents, with the run `ok`** (`source-data.md` 2).
4. ✓ **A typo in a table setting (`max_agee`) is silently taken as a connector option** (`first-use.md` 1).
5. ✓ **A secret with a trailing newline reaches the status view in clear text** (`security.md` 2).

## Lessons for the procedure

- A name filter in cleanup removed another agent's containers (`rv-shake-p1` matches `rv-shake-p18`). The
  brief now gives each agent its own label value.
- `docker rm -f` leaves the anonymous volume of every Postgres container behind: 15 after this run. The
  brief now asks for `docker run --rm` and `docker rm -fv`.
- Cost: six agents, about 500k subagent tokens, 8 minutes wall clock for the slowest (H2).
