"""Interactively provision a local user after applying database migrations."""

from argparse import ArgumentParser
from getpass import getpass

from finsight.infrastructure.database.session import SessionFactory
from finsight.services.identity import IdentityService


def main() -> int:
    parser = ArgumentParser(description="Create one local user account")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        parser.error("passwords do not match")
    try:
        user_id = IdentityService(SessionFactory).provision(args.email, password)
    except ValueError as error:
        parser.error(str(error))
    print(f"Created user {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
