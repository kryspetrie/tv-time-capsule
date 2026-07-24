"""CLI: store / delete secrets in the OS keychain."""

from __future__ import annotations

import argparse
import getpass
import sys

from .secrets import KEYRING_SERVICE, delete_secret, get_secret, set_secret


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            f"Manage TV Time Capsule secrets in the OS keychain "
            f"(service={KEYRING_SERVICE!r})"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="Store a secret (prompts for value)")
    p_set.add_argument("name", help="Keyring item name (e.g. nas-kids)")
    p_set.add_argument(
        "--value",
        help="Secret value (omit to prompt; prefer prompting so it stays out of shell history)",
    )

    p_get = sub.add_parser("get", help="Print whether a secret exists (not the value)")
    p_get.add_argument("name")

    p_del = sub.add_parser("delete", help="Delete a secret")
    p_del.add_argument("name")

    args = parser.parse_args(argv)

    try:
        if args.command == "set":
            value = args.value
            if value is None:
                value = getpass.getpass(f"Secret for {args.name!r}: ")
                confirm = getpass.getpass("Confirm: ")
                if value != confirm:
                    print("Values do not match", file=sys.stderr)
                    sys.exit(1)
            if not value:
                print("Empty secret not stored", file=sys.stderr)
                sys.exit(1)
            set_secret(args.name, value)
            print(f"Stored {KEYRING_SERVICE}/{args.name}")
        elif args.command == "get":
            existing = get_secret(args.name)
            if existing is None:
                print(f"missing: {KEYRING_SERVICE}/{args.name}")
                sys.exit(1)
            print(f"present: {KEYRING_SERVICE}/{args.name} ({len(existing)} chars)")
        elif args.command == "delete":
            delete_secret(args.name)
            print(f"Deleted {KEYRING_SERVICE}/{args.name}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
