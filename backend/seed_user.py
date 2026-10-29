"""Set a password for an existing account in a local database.

The previous version of this utility contained hardcoded operational
passwords and targeted fixed account IDs. Those credentials are removed.
This utility is now non-production only and requires:

    EDUSHIELD_ENV=development (or test/testing/local)
    EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET=1

The password is read interactively, never printed, and never stored in
the environment or shell history. Role and account status are not
changed.

Usage (from backend/):

    python seed_user.py <user_id> --apply

For test databases, set the environment explicitly, for example:

    set EDUSHIELD_ENV=test
    set EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET=1
    python seed_user.py <user_id> --apply
"""

import argparse
import getpass
import os
import sys

import mysql.connector

from auth import hash_password
from config import DB_CONFIG


MIN_PASSWORD_LENGTH = 12
ALLOWED_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


def _fail(message):
    print(f"seed_user: {message}", file=sys.stderr)
    return 1


def _validate_environment():
    environment = (os.getenv("EDUSHIELD_ENV") or "").strip().lower()

    if environment not in ALLOWED_ENVIRONMENTS:
        return (
            "refusing to run: EDUSHIELD_ENV must be one of "
            f"{', '.join(sorted(ALLOWED_ENVIRONMENTS))} "
            f"(got {environment or 'unset'})"
        )

    if os.getenv("EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET") != "1":
        return (
            "refusing to run: set "
            "EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET=1 for a non-production "
            "database"
        )

    return None


def _read_password():
    password = getpass.getpass("New password: ")

    if len(password) < MIN_PASSWORD_LENGTH:
        return None, (
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )

    confirmation = getpass.getpass("Confirm new password: ")

    if password != confirmation:
        return None, "passwords do not match"

    return password, None


def _reset_password(user_id, password):
    password_hash = hash_password(password)
    connection = mysql.connector.connect(**DB_CONFIG)
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE",
            (user_id,),
        )

        if not cursor.fetchone():
            connection.rollback()
            return "user not found"

        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s",
            (password_hash, user_id),
        )

        connection.commit()
        return None

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Reset one existing account password in a non-production "
            "database. The password is prompted, not printed."
        )
    )
    parser.add_argument("user_id", help="existing user ID to update")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="required acknowledgement that the password will be changed",
    )
    args = parser.parse_args(argv)

    if not args.apply:
        return _fail("refusing to change a password without --apply")

    environment_error = _validate_environment()

    if environment_error:
        return _fail(environment_error)

    typed_user_id = input(
        f"Type the user ID ({args.user_id}) to confirm: "
    ).strip()

    if typed_user_id != args.user_id:
        return _fail("user ID confirmation did not match")

    password, password_error = _read_password()

    if password_error:
        return _fail(password_error)

    try:
        reset_error = _reset_password(args.user_id, password)
    except Exception as exc:
        return _fail(f"password reset failed ({type(exc).__name__})")

    if reset_error:
        return _fail(reset_error)

    print(
        f"seed_user: password updated for {args.user_id}; "
        "value not shown."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
