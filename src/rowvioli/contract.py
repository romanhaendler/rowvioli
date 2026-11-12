"""The connector contract (decision 27): a module with `read(connection, table, options)` that returns an iterator of
Arrow batches, and optionally `tables(connection)` for `rowvioli list`. Connectors register as modules in the entry
point group `rowvioli.connectors` under their `type`; the shipped ones do the same."""
from importlib.metadata import entry_points


def connector(type):
    """The connector module registered under `type`, or None if none is installed."""
    found = entry_points(group="rowvioli.connectors", name=type)
    return next(iter(found)).load() if found else None
