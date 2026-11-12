# 05: Secrets, keys, a foreign connector

**Blocked by:** 03

**Status:** resolved

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** No value of a connection, and no password of a URL in it, appears in a reason, in `runs`, on stdout or on stderr, also when a driver or connector raises with the value in its message from deep inside. The run process catches every exception and turns it into a scrubbed reason; if it still dies, the worker reports `worker lost` (decides open point F4; record it in `docs/open-points.md`). Opening a ciphertext checks the source name, so a ciphertext copied to another source is rejected. The key file holds one or more private keys, one per line; a run picks the one whose `key_id` matches the source's, which makes the README's rotation work. A missing connector, an undecryptable connection or a ciphertext of another source fails with a reason naming the worker. A tiny connector package inside the test tree, installed into the test environment and registered under a test type through the entry point group, loads a table and can fail with connection values in its message.

- [x] The prototype's secret tests pass (stored ciphertext, copied ciphertext, wrong key, password nowhere)
- [x] A password with `@` and `%` written plainly loads the table; with the source refusing it, no part of it appears anywhere (spec test 5)
- [x] A connector failing with connection values in its message leaks none of them, also from deep inside (spec test 6)
- [x] A foreign connector installed through the entry point loads a table (spec test 16)
- [x] Key rotation: with old and new private key in the file, a worker loads after `apply` with the new public key; with only the old one, the run fails with a reason (spec test 20)

## Comments

- Scrubbing lives in `load.py` (`secrets`, `scrub`), applied once in `main` before `fail()`. It replaces with `***` every text value of the connection (nested too) and the password of a URL in it as written and decoded, longest first. Values are matched literally: a connector that re-encodes a value (repr with escaped backslashes, JSON escapes) before raising would not be caught.
- The prototype's "driver quotes a garbled password" test is gone: since `apply` percent-encodes a value in the user info (decision 32), libpq never misparses it. Replaced by spec test 5 (`Sesam@Torweg%zz-0815` loads, then refused, no part leaks). Quoting from deep inside is covered by the test connector (`fail = "deep"` raises inside the batch stream; ADBC wraps it as `IO: nanoarrow call failed: ...`).
- Test connector: `tests/connector` (package `rowvioli-testing`, type `testing`), installed as an editable path dependency of the dev group via `[tool.uv.sources]`. Tests in `tests/test_secrets.py`.
- Key rotation needed no code: `seal.unseal` already picked the key by `key_id` (03).
