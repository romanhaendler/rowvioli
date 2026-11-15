"""The connector contract (decision 27): a module with `read(connection, table, options)` that returns an iterator of
Arrow batches, and optionally `tables(connection)` for `rowvioli list`. Connectors register as modules in the entry
point group `rowvioli.connectors` under their `type`; the shipped ones do the same."""
from importlib.metadata import entry_points


def connector(type, where=""):
    """The connector module registered under `type`. Refuses if none is installed; `where` names the worker."""
    found = entry_points(group="rowvioli.connectors", name=type)
    if not found:
        installed = ", ".join(sorted({e.name for e in entry_points(group="rowvioli.connectors")}))
        raise SystemExit(f'connector "{type}" is not installed{where}; installed: {installed}')
    try:
        return next(iter(found)).load()
    except (ImportError, OSError) as e:  # a shipped connector without its extra, or without the library it loads
        raise SystemExit(f'connector "{type}" cannot be loaded{where}: {e}')
