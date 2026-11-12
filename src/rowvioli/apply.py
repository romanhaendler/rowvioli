"""Write the definition into the target. Needs no source and no driver for one."""
import base64
import json
import os
from importlib.resources import files

from . import definition, seal, target


def apply(directory, key_file):
    sources, tables, digest = definition.read(directory, os.environ)
    try:
        public = seal.public_key(key_file)
    except OSError as e:
        raise SystemExit(f"public key {key_file}: {e.strerror}")
    except Exception:
        raise SystemExit(f"{key_file} holds no public key")
    for s in sources:
        s["connection"] = base64.b64encode(seal.seal(public, s["name"], s["connection"])).decode()
        s["key_id"] = seal.key_id(public)
    conn = target.connect()
    payload = json.dumps({"sources": sources, "tables": tables, "definition": digest}, default=str)
    target.transaction(conn, files(__package__).joinpath("sql/apply.sql").read_text(), [payload])
    print(f"applied {len(sources)} sources with {len(tables)} tables")
