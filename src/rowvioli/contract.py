"""The connector contract (decision 27): a module with `read(connection, table, options)` that returns an iterator
of Arrow batches, and optionally `tables(connection)` for `rowvioli list`, `driver_version`, a string recorded with
every run, and `catalog` for a source without one of its own (decision 54): "data" where the columns are what the
data of one run hold, so that a column they lack is empty and never goes (file), or "definition" where they are what
the table names under `columns`, so that every change of them is the definition's (rest). Nothing is proven a rename
for either; without the entry the source has a catalog, as a database has. Connectors register as modules in the
entry point group `rowvioli.connectors` under their `type`; the shipped ones do the same."""
import importlib.metadata
from importlib.metadata import entry_points

# the metadata of an Arrow field whose type the file brings itself (Parquet), not a catalog nor a pin: it can change
# from one file to the next, so a change of its family stops (decision 54)
OWN_TYPE = {b"rowvioli:own_type": b"true"}


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


def known_options(type, table, options, known=()):
    """What a shipped connector does with an option it does not read: fails the run, naming the table, the
    option and the options it knows (decision 47). A connector of one's own decides for itself."""
    for name in options:
        if name not in known:
            raise Exception(f"{table}: the option {name} is not one of the {type} connector's; it knows "
                            + (", ".join(known) or "no option"))


def version(package):
    """A shipped connector's `driver_version`: the package it reads with and its version, or none for a package
    installed without its metadata, which a run does not need."""
    try:
        return f"{package} {importlib.metadata.version(package)}"
    except importlib.metadata.PackageNotFoundError:
        return None
