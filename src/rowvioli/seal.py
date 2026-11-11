"""Worker key and sealed connections (libsodium sealed box, decision 26)."""
import hashlib
import json
import os

from nacl.encoding import Base64Encoder
from nacl.public import PrivateKey, PublicKey, SealedBox

PRIVATE, PUBLIC = "worker.key", "worker.pub"


def new_keypair(dir="."):
    """Writes worker.key (mode 600) and worker.pub, both base64. Never overwrites a key."""
    priv, pub = os.path.join(dir, PRIVATE), os.path.join(dir, PUBLIC)
    for path in (priv, pub):
        if os.path.exists(path):
            raise SystemExit(f"{path} exists, not overwriting it")
    key = PrivateKey.generate()
    with os.fdopen(os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(key.encode(Base64Encoder) + b"\n")
    with open(pub, "xb") as f:
        f.write(key.public_key.encode(Base64Encoder) + b"\n")


def key_id(public_key):
    return hashlib.sha256(bytes(public_key)).hexdigest()[:16]


def load_public(path):
    return PublicKey(open(path, "rb").read().strip(), Base64Encoder)


def load_private(path=None):
    return PrivateKey(open(path or os.environ["ROWVIOLI_KEY_FILE"], "rb").read().strip(), Base64Encoder)


def seal(public_key, name, block):
    """The source name is sealed with its block, so a ciphertext copied to another source is rejected."""
    return SealedBox(public_key).encrypt(json.dumps({"name": name, "connection": block}).encode())


def open_(private_key, name, blob):
    d = json.loads(SealedBox(private_key).decrypt(blob))
    if d["name"] != name:
        raise ValueError(f"the connection of source {name} was sealed for another source")
    return d["connection"]
