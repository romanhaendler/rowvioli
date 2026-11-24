"""The control connection to the target: keepalive, schema version, SQL (decision 28: ADBC only)."""
import os
import re
from importlib.resources import files

import adbc_driver_postgresql.dbapi as adbc

SCHEMA_VERSION = 4
# schema.sql is version 3; the step at index i brings version 3 + i to 3 + i + 1 (decision 54), with what a worker's
# role needs on the objects it creates: the program grants nothing, so init prints it
MIGRATIONS = [("sql/migrate_3_4.sql", "GRANT SELECT, INSERT, UPDATE, DELETE ON _rowvioli.columns TO worker;\n"
                                      "GRANT SELECT, INSERT ON _rowvioli.columns__log TO worker;")]

# docs/target.md "Failures": a dead client or network is noticed by Postgres within seconds to a minute. The URL's
# keepalive is libpq's, so the worker notices a dead server; SESSION is the server's, so Postgres notices a dead worker
# and frees its locks (measured: 62 s after the network was cut, without it still held after 240 s)
KEEPALIVE = "keepalives_idle=30&keepalives_interval=10&keepalives_count=3&tcp_user_timeout=60000"
SESSION = {"client_connection_check_interval": "2s", "tcp_keepalives_idle": "30", "tcp_keepalives_interval": "10",
           "tcp_keepalives_count": "3", "tcp_user_timeout": "60000"}

# what a worker may start and a run may claim, asked with the same counts by both (decision 34)
CLAIMABLE = files(__package__).joinpath("sql/claimable.sql").read_text()


NO_SCHEMA = "the target has no schema _rowvioli: run `rowvioli init` first"


def check_address(url):
    """Fails before connecting for an address that is no postgres URL, or has a second @, which the driver would
    read as part of the host. Never prints the address: it may hold a password."""
    if not url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("ROWVIOLI_TARGET_URL must start with postgresql:// or postgres://")
    if url.split("://", 1)[-1].split("?", 1)[0].count("@") > 1:
        raise SystemExit("ROWVIOLI_TARGET_URL has more than one @ after the scheme: a password with @, / or : "
                         "must be percent-encoded")
    rest = url.split("://", 1)[1]
    authority = re.split(r"[/?]", rest, maxsplit=1)[0]  # not at #: the driver takes a # in a password as it is
    host = authority.rsplit("]", 1)[-1]  # after an IPv6 host's bracket, so its colons are no user info
    port = host.rsplit(":", 1)[-1]
    # a password holding / or ? ends the authority early: what is left looks like host:word with an @ further on.
    # Several hosts (a comma) and an empty port are the driver's to judge.
    if (":" in host and "@" not in authority and "," not in authority and port and not port.isdigit()
            and "@" in rest[len(authority):]):
        raise SystemExit("ROWVIOLI_TARGET_URL: the password holds a / or ?, which must be percent-encoded "
                         "(%2F, %3F)")


def connect(init=False, versioned=True, pooler=True):
    """Opens the control connection and refuses a target without `_rowvioli` or with another schema version.
    With init=True a missing `_rowvioli` is created instead. With versioned=False only the status view must
    exist: a role that may only read it cannot read `meta` (docs/operation.md "The target"). With pooler=False the
    check for a pooler in transaction mode is left out: a run process's worker has made it (decision 55)."""
    url = os.environ.get("ROWVIOLI_TARGET_URL")
    if not url:
        raise SystemExit("ROWVIOLI_TARGET_URL is not set")
    check_address(url)
    url += ("&" if "?" in url else "?") + KEEPALIVE
    conn = adbc.connect(url, autocommit=True)
    pooled = False
    try:
        for name, value in SESSION.items():
            sql(conn, f"SET {name} = '{value}'")
        if pooler:
            # Postgres gives every connection a server process of its own for its life. A pooler in transaction mode
            # hands one to whichever client asks next: an idle one hands this connection's to the next client too, a
            # busy one moves this connection between two transactions (decision 55)
            [(pid,)] = sql(conn, "SELECT pg_backend_pid()")  # one transaction each (autocommit)
            with adbc.connect(url, autocommit=True) as other:
                pooled = sql(other, "SELECT pg_backend_pid()") == [(pid,)]
            pooled = pooled or sql(conn, "SELECT pg_backend_pid()") != [(pid,)]
    except adbc.Error as e:  # a very busy one gives the driver's statement to another client's transaction
        if not pooler or e.sqlstate not in ("26000", "08P01"):  # invalid_sql_statement_name, protocol_violation
            raise
        pooled = True
    if pooled:
        raise SystemExit("a connection pooler in transaction mode is in front of the target; use session mode or "
                         "connect directly")
    if not versioned:
        if not sql(conn, "SELECT to_regclass('_rowvioli.status') IS NOT NULL")[0][0]:
            raise SystemExit(NO_SCHEMA)
        return conn
    version = None
    if sql(conn, "SELECT to_regclass('_rowvioli.meta') IS NOT NULL")[0][0]:
        version = sql(conn, "SELECT schema_version FROM _rowvioli.meta")[0][0]
    if init and (version is None or 3 <= version < SCHEMA_VERSION):  # below 3 there is no step: refused below
        steps = [step for step, _ in MIGRATIONS[0 if version is None else version - 3:]]
        steps = ["sql/schema.sql", *steps] if version is None else steps
        transaction(conn, "".join(files(__package__).joinpath(step).read_text() for step in steps))
        if version is not None:
            print(f"the schema _rowvioli is brought from version {version} to {SCHEMA_VERSION}; a worker's role needs "
                  "these rights on its new objects, which the program does not grant (worker stands for that role):\n"
                  + "\n".join(grants for _, grants in MIGRATIONS[version - 3:]))
        version = SCHEMA_VERSION
    if version is None:
        raise SystemExit(NO_SCHEMA)
    if version != SCHEMA_VERSION:
        raise SystemExit(f"the target has schema version {version}, this program works with version {SCHEMA_VERSION}"
                         + (f"; rowvioli init brings it to {SCHEMA_VERSION}" if 3 <= version < SCHEMA_VERSION else ""))
    return conn


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def literal(text):
    return "'" + text.replace("'", "''") + "'"


def sql(conn, query, params=None):
    """Runs one statement. Returns all rows, or None for a statement without a result."""
    with conn.cursor() as c:
        c.execute(query, params)
        return c.fetchall() if c.description else None


def transaction(conn, script, params=None):
    """Runs the statements of a script (separated by `;` at a line end) in one transaction, each with params."""
    sql(conn, "BEGIN")
    try:
        for statement in script.split(";\n"):
            if statement.strip():
                sql(conn, statement, params)
        sql(conn, "COMMIT")
    except BaseException:
        sql(conn, "ROLLBACK")
        raise
