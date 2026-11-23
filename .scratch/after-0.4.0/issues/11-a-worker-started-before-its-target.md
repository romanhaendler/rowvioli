# 11: The systemd unit of `docs/operation.md` gives up when the target comes up after the worker

**Status:** ready-for-agent

**Model:** Sonnet

From `.scratch/shakedown/sixth-run.md` (H4). Confirmed in the source: `loop` connects once before its loop, so a worker started while the target is down exits 1 at once; the retry every two seconds exists only after a first connection. The unit has `Restart=always` without `RestartSec`, so systemd restarts it five times within a second and then leaves it failed (reasoned, not run under systemd). `ExecStart=rowvioli work` is no absolute path, and `uv tool install` puts the program into `~/.local/bin` (lead, not run).

Docs only, the program stays as it is (a worker that cannot reach its target at the start fails fast, so a wrong address is seen at once):

- The unit gets `RestartSec=5` and no start limit, an absolute `ExecStart` with a sentence on where the program is, and one sentence on why.
- The container paragraph says the same for a restart policy.
