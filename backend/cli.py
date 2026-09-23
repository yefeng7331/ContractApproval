"""Interactive local account provisioning; passwords never appear in arguments."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from backend.auth import AuthStore, ROLES
from backend.main import default_database_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local demo users")
    parser.add_argument("--database", type=Path, default=default_database_path())
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Create a local test account")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=ROLES, required=True)
    args = parser.parse_args()

    password = getpass.getpass("Password (at least 12 characters): ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        parser.error("Passwords do not match")

    store = AuthStore(args.database)
    try:
        store.initialize()
        user = store.create_user(args.username, args.role, password)
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        store.close()
    print(f"Created {user.username} ({user.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
