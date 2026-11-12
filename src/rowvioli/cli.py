"""The commands: arguments, the answer on stdout, the exit code."""
import argparse

from . import seal, target


def main():
    p = argparse.ArgumentParser(prog="rowvioli")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the schema _rowvioli in the target")
    sub.add_parser("key", help="create a key pair").add_argument("action", choices=["new"])
    sub.add_parser("list", help="print the tables of a source").add_argument("source")
    ap = sub.add_parser("apply", help="write the definition into the target")
    ap.add_argument("directory")
    ap.add_argument("--check", action="store_true", help="only read and check the definition")
    ap.add_argument("--key", default="worker.pub", help="public key file")
    rp = sub.add_parser("run", help="load what is due, once")
    rp.add_argument("source", nargs="?")
    rp.add_argument("table", nargs="?")
    rp.add_argument("--slots", type=int, default=4)
    sub.add_parser("work", help="load what is due, permanently").add_argument("--slots", type=int, default=4)
    a = p.parse_args()

    if a.command == "init":
        target.connect(init=True)
    elif a.command == "key":
        seal.new_key()
    else:
        if a.command in ("apply", "run", "work") and not getattr(a, "check", False):
            target.connect()
        raise SystemExit(f"rowvioli {a.command}: not built yet")
