"""The control connection: one ADBC connection to the target (decision 28)."""
import os

import adbc_driver_postgresql.dbapi as adbc

# README "Failures": the program sets these on its own connections
KEEPALIVE = "keepalives_idle=30&keepalives_interval=10&keepalives_count=3&tcp_user_timeout=60000"


def connect(url=None):
    url = url or os.environ["ROWVIOLI_TARGET_URL"]
    conn = adbc.connect(url + ("&" if "?" in url else "?") + KEEPALIVE, autocommit=True)
    sql(conn, "SET client_connection_check_interval = '2s'")
    return conn


def sql(conn, query, params=None):
    """Run one statement. Returns all rows, or None for a statement without result."""
    with conn.cursor() as c:
        c.execute(query, params)
        return c.fetchall() if c.description else None
