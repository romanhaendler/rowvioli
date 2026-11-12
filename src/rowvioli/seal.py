"""The worker key pair and sealed connections (libsodium sealed box, decisions 15 and 26)."""
import os

from nacl.encoding import Base64Encoder
from nacl.public import PrivateKey


def new_key():
    """Writes worker.key (mode 600) and worker.pub into the current directory, base64, one key per line.
    Overwrites neither."""
    for path in ("worker.key", "worker.pub"):
        if os.path.exists(path):
            raise SystemExit(f"{path} exists, not overwriting it")
    key = PrivateKey.generate()
    # O_EXCL: a file created meanwhile is not overwritten either
    with os.fdopen(os.open("worker.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(key.encode(Base64Encoder) + b"\n")
    with open("worker.pub", "xb") as f:
        f.write(key.public_key.encode(Base64Encoder) + b"\n")
