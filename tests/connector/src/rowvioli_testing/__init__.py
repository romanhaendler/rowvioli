"""Delivers the option `rows` as a table with one column `n`. With the option `fail` it raises with the connection,
its values and the password of its URL in the message: `at_once` when called, `deep` from a nested call while the
batches are read. With the option `print` it writes the connection to stderr, as a chatty driver might."""
import os
from urllib.parse import unquote, urlsplit

import pyarrow as pa


def read(connection, table, options):
    if options.get("print"):
        os.write(2, f"connecting with {connection}\n".encode())
    if options.get("fail") == "at_once":
        leak(connection)
    return batches(connection, options)


def batches(connection, options):
    yield pa.record_batch({"n": options.get("rows", [1, 2, 3])})
    if options.get("fail") == "deep":
        leak(connection)


def leak(connection):
    password = unquote(urlsplit(connection["url"]).password)
    raise RuntimeError(f"cannot connect with {connection} as {password}, token {connection['token']}")
