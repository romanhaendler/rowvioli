"""The control connection to the target: keepalive, schema version, SQL (decision 28: ADBC only)."""
import os
from importlib.resources import files

import adbc_driver_postgresql.dbapi as adbc

SCHEMA_VERSION = 3

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


def connect(init=False, versioned=True):
    """Opens the control connection and refuses a target without `_rowvioli` or with another schema version.
    With init=True a missing `_rowvioli` is created instead. With versioned=False only the status view must
    exist: a role that may only read it cannot read `meta` (docs/operation.md "The target")."""
    url = os.environ.get("ROWVIOLI_TARGET_URL")
    if not url:
        raise SystemExit("ROWVIOLI_TARGET_URL is not set")
    check_address(url)
    conn = adbc.connect(url + ("&" if "?" in url else "?") + KEEPALIVE, autocommit=True)
    for name, value in SESSION.items():
        sql(conn, f"SET {name} = '{value}'")
    if sql(conn, "SELECT pg_backend_pid()") != sql(conn, "SELECT pg_backend_pid()"):  # one per transaction (autocommit)
        raise SystemExit("a connection pooler in transaction mode is in front of the target; use session mode")
    if not versioned:
        if not sql(conn, "SELECT to_regclass('_rowvioli.status') IS NOT NULL")[0][0]:
            raise SystemExit(NO_SCHEMA)
        return conn
    version = None
    if sql(conn, "SELECT to_regclass('_rowvioli.meta') IS NOT NULL")[0][0]:
        version = sql(conn, "SELECT schema_version FROM _rowvioli.meta")[0][0]
    if version is None and init:
        transaction(conn, files(__package__).joinpath("sql/schema.sql").read_text())
        version = SCHEMA_VERSION
    if version is None:
        raise SystemExit(NO_SCHEMA)
    if version != SCHEMA_VERSION:
        raise SystemExit(f"the target has schema version {version}, this program works with version {SCHEMA_VERSION}")
    return conn


def quote(name):
    return '"' + name.replace('"', '""') + '"'


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
