"""Read and check the source files, fill in placeholders."""
import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
# a table may override these; its row carries them with the source's filled in
TABLE_SETTINGS = {"max_age": str, "log": bool, "max_delete_share": (int, float), "max_seconds": int, "at": list,
                  "timezone": str, "target_schema": str}
# settings of a table only, not of the source and not a connector option
TABLE_ONLY = {"key": list, "target_table": str}
DEFAULTS = {"log": True, "max_delete_share": 0.5, "max_seconds": 3600}
SOURCE_SETTINGS = {"type": str, "connection": dict, "tables": dict, "parallel": int,
                   **TABLE_SETTINGS}
RANGES = {"parallel": (lambda v: v >= 1, "at least 1"), "max_delete_share": (lambda v: 0 <= v <= 1, "between 0 and 1"),
          "max_seconds": (lambda v: v > 0, "greater than 0")}
KINDS = {str: "a string", bool: "true or false", int: "a whole number", (int, float): "a number", dict: "a table",
         list: "a list"}
# `$NAME`, `$$`, or a `$` that is neither (group 1 is None)
PLACEHOLDER = re.compile(r"\$(\$|[A-Z][A-Z0-9_]*)?")
# group 1 is the user info of a URL: `scheme://user:password@`
USERINFO = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:([^/?#]*)@)?")


def read(directory, env=None, only=None):
    """Reads and checks every *.toml in the directory. With env, the placeholders of each connection are filled in
    from it; without, they are only checked. With `only`, just that source's are filled: `list` needs no other
    source's secrets. Returns (sources, tables, hash of the definition)."""
    if not Path(directory).is_dir():
        raise SystemExit(f"{directory} is not a directory")
    whole, sources, tables, names = {}, [], [], {}
    files = sorted(Path(directory).glob("*.toml"))
    if not files:
        raise SystemExit(f"{directory} holds no source files (*.toml); applying it would disable every table")
    for path in files:
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
            typos(s, where)
            for k in TABLE_ONLY.keys() & s.keys():  # one table's, so no default for all, no connector option either
                raise SystemExit(f"{where}: {k} belongs to a table, not to the source")
            for required in ("type", "max_age", "connection", "tables"):
                if required not in s:
                    raise SystemExit(f"{where}: {required} is missing")
            interval(s["max_age"], where)
            sources.append({"name": name, "type": s["type"], "parallel": s.get("parallel", 2),
                            "options": {k: v for k, v in s.items() if k not in SOURCE_SETTINGS},
                            "connection": fill(s["connection"], f"{where}: connection",
                                              env if only in (None, name) else None)})
            for table, t in s["tables"].items():
                spot = f"{where}: {table}"
                settings(t, {**TABLE_SETTINGS, **TABLE_ONLY}, spot)
                typos(t, spot)
                for k in (SOURCE_SETTINGS.keys() - TABLE_SETTINGS.keys()) & t.keys():
                    raise SystemExit(f"{spot}: {k} belongs to the source, not to a table")
                key = t.get("key")
                if key is not None and not (key and all(isinstance(c, str) and c for c in key)):
                    raise SystemExit(f"{spot}: key must be a list of column names")
                # a file's extension is not a name part: `customers.csv` becomes `customers`
                target = t["target_table"] if "target_table" in t else (
                    Path(table).stem if s["type"] == "file" else table.rsplit(".", 1)[-1]).lower()
                schema = t.get("target_schema", s.get("target_schema", f"raw_{name}"))
                # Postgres cuts names at 63 bytes; the change log and the history view add `__log`, `__history`
                if len(schema.encode()) > 63:
                    raise SystemExit(f"{spot}: target_schema {schema} is longer than 63 bytes")
                if len(target.encode()) > 54:
                    raise SystemExit(f"{spot}: target table {target} is longer than 54 bytes")
                if not schema or not target or schema == "_rowvioli":
                    raise SystemExit(f"{spot}: target_schema and target_table must not be empty, "
                                     "and the schema must not be _rowvioli")
                for suffix in ("", "__log", "__history"):
                    if (schema, target + suffix) in names:
                        first_path, first = names[schema, target + suffix]
                        both = (f"{first_path}: {first} and {path.name}: {name}: {table}" if first_path != path.name
                                else f"{path.name}: {first} and {name}: {table}")
                        raise SystemExit(f"{both} both become {schema}.{target + suffix}; "
                                         "set target_table at one of them")
                    names[schema, target + suffix] = path.name, f"{name}: {table}"
                if s["type"] == "rest" and not str(t.get("path", "/")).startswith("/"):
                    raise SystemExit(f"{spot}: path must start with /")
                # no default zone: 14:00 that silently means UTC is found in production (decision 36)
                times = {k: t.get(k, s.get(k)) for k in ("at", "timezone")}
                if times["at"] and not times["timezone"]:
                    raise SystemExit(f"{spot}: at needs a timezone, from the table or the source")
                tables.append({"source": name, "source_table": table, "target_schema": schema,
                               "target_table": target, "key": key,
                               "max_age": interval(t.get("max_age", s["max_age"]), spot),
                               **{k: t.get(k, s.get(k, DEFAULTS[k])) for k in DEFAULTS},
                               **times,
                               "options": {k: v for k, v in t.items()
                                           if k not in TABLE_SETTINGS and k not in TABLE_ONLY}})
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
        if k in block and k in RANGES and not RANGES[k][0](block[k]):
            raise SystemExit(f"{where}: {k} must be {RANGES[k][1]}")
    for time in block.get("at", []):
        if not (isinstance(time, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time)):
            raise SystemExit(f"{where}: at {time!r} is not a time HH:MM from 00:00 to 23:59")
    if "timezone" in block:
        try:
            ZoneInfo(block["timezone"])
        except (KeyError, ValueError, OSError):  # not found, not a zone's name, a directory
            raise SystemExit(f"{where}: timezone {block['timezone']!r} is not a time zone")


def edits(a, b):
    """Edit distance of two words (insert, delete, replace)."""
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def typos(block, where):
    """A key that is no setting but a typo of one would silently go to the connector as an option. Short words
    are left alone (`sep` is one edit from nothing but two from `key`): shortcut: one edit under 6 letters."""
    known = SOURCE_SETTINGS.keys() | TABLE_ONLY.keys()
    for k in block.keys() - known:
        for setting in known:
            if len(k) >= 4 and edits(k, setting) <= (2 if len(setting) >= 6 else 1):
                raise SystemExit(f"{where}: {k} is not a setting; did you mean {setting}? "
                                 "(other keys go to the connector as options)")


def interval(value, where):
    m = re.fullmatch(r"([1-9]\d*)([smhd])", value)
    if not m:
        raise SystemExit(f"{where}: max_age {value!r} is not a whole number with s, m, h or d")
    return f"{m[1]} {UNITS[m[2]]}"


def duration(seconds):
    """Seconds as a person reads them, the largest two units: `5m`, `1h 3m`. For the status, not for the definition."""
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size and len(parts) < 2:
            parts.append(f"{seconds // size}{unit}")
            seconds %= size
    return " ".join(parts) or "0s"


def fill(template, where, env):
    """`$NAME` from env, `$$` a literal `$`, in every string of the connection, also nested ones. A value landing
    in the user info of a URL is percent-encoded (decision 32). Without env, the placeholders are only checked. No
    value ever appears in an error."""
    if isinstance(template, dict):
        return {k: fill(v, f"{where}.{k}", env) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, where, env) for v in template]
    if not isinstance(template, str):
        return template
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
