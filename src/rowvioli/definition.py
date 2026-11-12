"""Read and check the source files, fill in placeholders."""
import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote

UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
# a table may override these; its row carries them with the source's filled in
TABLE_SETTINGS = {"max_age": str, "log": bool, "max_delete_share": (int, float), "max_seconds": int}
DEFAULTS = {"log": True, "max_delete_share": 0.5, "max_seconds": 3600}
SOURCE_SETTINGS = {"type": str, "connection": dict, "tables": dict, "target_schema": str, "parallel": int,
                   **TABLE_SETTINGS}
KINDS = {str: "a string", bool: "true or false", int: "a whole number", (int, float): "a number", dict: "a table",
         list: "a list"}
# `$NAME`, `$$`, or a `$` that is neither (group 1 is None)
PLACEHOLDER = re.compile(r"\$(\$|[A-Z][A-Z0-9_]*)?")
# group 1 is the user info of a URL: `scheme://user:password@`
USERINFO = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:([^/?#]*)@)?")


def read(directory, env=None):
    """Reads and checks every *.toml in the directory. With env, the placeholders of each connection are filled in
    from it; without, they are only checked. Returns (sources, tables, hash of the definition)."""
    if not Path(directory).is_dir():
        raise SystemExit(f"{directory} is not a directory")
    whole, sources, tables, schemas = {}, [], [], {}
    for path in sorted(Path(directory).glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise SystemExit(f"{path.name}: {e}")
        for name, s in data.items():
            where = f"{path.name}: {name}"
            if name in whole:
                raise SystemExit(f"{where}: source {name} is defined twice")
            whole[name] = s
            settings(s, SOURCE_SETTINGS, where)
            for required in ("type", "max_age"):
                if required not in s:
                    raise SystemExit(f"{where}: {required} is missing")
            interval(s["max_age"], where)
            schema = s.get("target_schema", f"raw_{name}")
            if schema in schemas:
                raise SystemExit(f"{where}: target_schema {schema} belongs to source {schemas[schema]} already")
            schemas[schema] = name
            sources.append({"name": name, "type": s["type"], "target_schema": schema, "parallel": s.get("parallel", 2),
                            "options": {k: v for k, v in s.items() if k not in SOURCE_SETTINGS},
                            "connection": {k: fill(v, f"{where}: connection.{k}", env) if isinstance(v, str) else v
                                           for k, v in s.get("connection", {}).items()}})
            seen = {}
            for table, t in s.get("tables", {}).items():
                at = f"{where}: {table}"
                settings(t, {**TABLE_SETTINGS, "key": list}, at)
                key = t.get("key")
                if key is not None and not (key and all(isinstance(c, str) and c for c in key)):
                    raise SystemExit(f"{at}: key must be a list of column names")
                # a file's extension is not a name part: `customers.csv` becomes `customers`
                target = (Path(table).stem if s["type"] == "file" else table.rsplit(".", 1)[-1]).lower()
                if target in seen:
                    raise SystemExit(f"{at}: {seen[target]} and {table} both become target table {target}")
                seen[target] = table
                tables.append({"source": name, "source_table": table, "target_table": target, "key": key,
                               "max_age": interval(t.get("max_age", s["max_age"]), at),
                               **{k: t.get(k, s.get(k, DEFAULTS[k])) for k in DEFAULTS},
                               "options": {k: v for k, v in t.items() if k not in TABLE_SETTINGS and k != "key"}})
    # of the text as written: placeholders stay unfilled, so the hash says nothing about a secret
    digest = hashlib.sha256(json.dumps(whole, sort_keys=True, default=str).encode()).hexdigest()
    return sources, tables, digest


def settings(block, known, where):
    """Checks that a source or table is a table and that its known settings have the right kind of value."""
    if not isinstance(block, dict):
        raise SystemExit(f"{where}: must be a table")
    for k, kind in known.items():
        # bool is a subclass of int, so true must not pass as a whole number and 1 not as true
        if k in block and (not isinstance(block[k], kind) or isinstance(block[k], bool) != (kind is bool)):
            raise SystemExit(f"{where}: {k} must be {KINDS[kind]}")


def interval(value, where):
    m = re.fullmatch(r"([1-9]\d*)([smhd])", value)
    if not m:
        raise SystemExit(f"{where}: max_age {value!r} is not a whole number with s, m, h or d")
    return f"{m[1]} {UNITS[m[2]]}"


def fill(template, where, env):
    """`$NAME` from env, `$$` a literal `$`. A value landing in the user info of a URL is percent-encoded
    (decision 32). Without env, the placeholders are only checked. No value ever appears in an error."""
    url = USERINFO.match(template)
    userinfo_end = url.end(1) if url and url[1] is not None else -1

    def sub(m):
        if m[1] is None:
            raise SystemExit(f"{where}: a $ must start a placeholder like $NAME or be written $$")
        if m[1] == "$" or env is None:
            return "$"
        if m[1] not in env:
            raise SystemExit(f"{where}: variable {m[1]} is not set")
        return quote(env[m[1]], safe="") if m.start() < userinfo_end else env[m[1]]
    return PLACEHOLDER.sub(sub, template)
