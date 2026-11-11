import argparse
import sys


def main():
    p = argparse.ArgumentParser(prog="rowvioli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("key").add_argument("action", choices=["new"])
    ap = sub.add_parser("apply")
    ap.add_argument("directory")
    ap.add_argument("--key", default="worker.pub", help="public key file")
    for name in ("run", "work"):
        sub.add_parser(name)
    a, _ = p.parse_known_args()

    if a.cmd == "apply":
        from . import apply, control
        with control.connect() as conn:
            apply.apply(conn, a.directory, a.key)
        return
    if a.cmd == "init":
        from . import control, schema
        with control.connect() as conn:
            schema.init(conn)
        return
    if a.cmd == "key":
        from . import seal
        seal.new_keypair()
        return
    sys.exit(f"rowvioli {a.cmd}: not implemented")
