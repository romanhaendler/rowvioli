# 05: Secrets, keys, a foreign connector

**Blocked by:** 03

**Status:** ready-for-agent

Spec: `.scratch/v0.1/spec.md`. Behaviour reference: `README.md`, `GLOSSARY.md`, `docs/decisions.md`. Prototype findings: `.scratch/prototype/findings.md`; prototype code on branch `prototype-impl` may be read, not copied as a base.

**What to build:** No value of a connection, and no password of a URL in it, appears in a reason, in `runs`, on stdout or on stderr, also when a driver or connector raises with the value in its message from deep inside. The run process catches every exception and turns it into a scrubbed reason; if it still dies, the worker reports `worker lost` (decides open point F4; record it in `docs/open-points.md`). Opening a ciphertext checks the source name, so a ciphertext copied to another source is rejected. The key file holds one or more private keys, one per line; a run picks the one whose `key_id` matches the source's, which makes the README's rotation work. A missing connector, an undecryptable connection or a ciphertext of another source fails with a reason naming the worker. A tiny connector package inside the test tree, installed into the test environment and registered under a test type through the entry point group, loads a table and can fail with connection values in its message.

- [ ] The prototype's secret tests pass (stored ciphertext, copied ciphertext, wrong key, password nowhere)
- [ ] A password with `@` and `%` written plainly loads the table; with the source refusing it, no part of it appears anywhere (spec test 5)
- [ ] A connector failing with connection values in its message leaks none of them, also from deep inside (spec test 6)
- [ ] A foreign connector installed through the entry point loads a table (spec test 16)
- [ ] Key rotation: with old and new private key in the file, a worker loads after `apply` with the new public key; with only the old one, the run fails with a reason (spec test 20)
