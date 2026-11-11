"""Worker key and sealed connections (libsodium sealed box, decision 26)."""
import os

from nacl.encoding import Base64Encoder
from nacl.public import PrivateKey

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
