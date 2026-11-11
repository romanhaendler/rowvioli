"""Reading the definition directory and filling in placeholders (spec "Definition")."""
import os
import re
import tomllib
from pathlib import Path

UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
SOURCE_SETTINGS = ("parallel", "max_delete_share", "max_seconds")


def interval(value, where):
    m = re.fullmatch(r"(\d+)([smhd])", str(value))
    if not m:
        raise SystemExit(f"{where}: max_age {value!r} is not a whole number with s, m, h or d")
    return f"{m[1]} {UNITS[m[2]]}"


def fill(value, where, env):
    """`$NAME` from the environment, `$$` a literal dollar. A missing variable aborts."""
    def sub(m):
        if m[0] == "$$":
            return "$"
        if m[1] not in env:
            raise SystemExit(f"{where}: variable {m[1]} is not set")
        return env[m[1]]
    return re.sub(r"\$\$|\$([A-Z][A-Z0-9_]*)", sub, value) if isinstance(value, str) else value


def read(directory, env=os.environ):
    """Returns (sources, tables) as plain dicts. Each source carries its filled-in `connection` block."""
    sources, tables = [], []
    for path in sorted(Path(directory).glob("*.toml")):
        for name, s in tomllib.loads(path.read_text()).items():
            where = f"{path.name}: {name}"
            for required in ("type", "max_age"):
                if required not in s:
                    raise SystemExit(f"{where}: {required} is missing")
            sources.append({"name": name, "type": s["type"],
                            "target_schema": s.get("target_schema", f"raw_{name}"),
                            **{k: s[k] for k in SOURCE_SETTINGS if k in s},
                            "connection": {k: fill(v, where, env) for k, v in s.get("connection", {}).items()}})
            seen = {}
            for table, t in s.get("tables", {}).items():
                target = table.rsplit(".", 1)[-1].lower()
                if target in seen:
                    raise SystemExit(f"{where}: {seen[target]} and {table} both become target table {target}")
                seen[target] = table
                tables.append({"source": name, "source_table": table, "target_table": target,
                               "key": t.get("key"), "max_age": interval(t.get("max_age", s["max_age"]), where)})
    return sources, tables
