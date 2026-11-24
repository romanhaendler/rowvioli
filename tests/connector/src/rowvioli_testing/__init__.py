"""Delivers the option `rows` (or `columns`, as it arrives) as a table with one column `n`, or `records`, objects, a
column per key. With the option `fail` it raises with the connection,
its values and the password of its URL (and of an ODBC `string`) in the message: `at_once` when called, `deep` from
a nested call while the batches are read. With the option `print` it writes the connection to stderr, as a chatty
driver might, and a progress bar to stdout, as DuckDB does."""
import os
import re
from urllib.parse import unquote

import pyarrow as pa

driver_version = os.environ.get("ROWVIOLI_TEST_DRIVER_VERSION")  # what the contract's optional `driver_version` reports
catalog = os.environ.get("ROWVIOLI_TEST_CATALOG")  # what the contract's optional `catalog` says


def read(connection, table, options):
    if options.get("print"):
        os.write(2, f"connecting with {connection}\n".encode())
        print("\r 98% ▕████▏", end="", flush=True)
    if options.get("fail") == "at_once":
        leak(connection)
    if options.get("fail") == "empty":  # an exception whose message is empty
        raise KeyError
    if "columns" in options:  # delivered as rows, to show how the option arrived
        options = {**options, "rows": options["columns"]}
    if options.get("nothing"):  # not even a batch with the columns
        return iter(())
    return batches(connection, options)


def batches(connection, options):
    if "records" in options:  # objects, a column per key
        yield pa.RecordBatch.from_pylist(options["records"])
        return
    yield pa.record_batch({"n": options.get("rows", [1, 2, 3])})
    if options.get("fail") == "deep":
        leak(connection)


def leak(connection):
    password = unquote(re.match(r"\w+://[^:]*:(.*)@", connection["url"], re.S)[1])  # urlsplit drops a newline
    odbc = re.search(r"PWD\s*=\s*\{?([^;}]*)", connection.get("string", ""), re.I)  # unbraced, as a driver may
    raise RuntimeError(f"cannot connect with {connection} as {password}, token {connection['token']}"
                       + (f", password {odbc[1]}" if odbc else ""))
