# 12: Two messages that name the wrong cause

**Status:** ready-for-agent

**Model:** Sonnet

From `.scratch/shakedown/sixth-run.md` (P1).

- `ROWVIOLI_TARGET_URL=localhost rowvioli status` says `invalid connection option "localhost?keepalives_idle"`: the option is ours. An address that does not start with `postgresql://` or `postgres://` gets a message that says so, without printing the address (it may hold a password).
- A table that was mirrored with a key and then has no `key` in the definition fails with `the key [] differs from the mirror's primary key […]; the change log … exists: drop it …`. For an empty key the reason says that the definition has no key any more, names the key of the mirror and both ways out (put the key back, or give the table another `target_table`); the existing reason stays for a key that changed.

Test first, each asserting what a person sees.
