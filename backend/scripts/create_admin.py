"""
Create (or promote) the bootstrap admin account.

Usage (from backend/, with the venv active):

    python scripts/create_admin.py

Reads ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD from the
environment (see backend/.env). The password is hashed with the same
function the app uses and is never printed or logged.

Safe to re-run for creation, but it never silently changes an existing
account: pass --update-existing to reset that account's password and
force its role to 'admin'. Clear ADMIN_BOOTSTRAP_PASSWORD afterwards.
"""

import argparse
import os
import secrets
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from auth import hash_password  # noqa: E402
from config import (  # noqa: E402
    ADMIN_BOOTSTRAP_EMAIL,
    ADMIN_BOOTSTRAP_PASSWORD,
    DB_CONFIG,
)

import mysql.connector  # noqa: E402

MIN_PASSWORD_LENGTH = 12


def _fail(message):
    print(f"create_admin: {message}", file=sys.stderr)
    return 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Create or explicitly update the bootstrap admin account."
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help=(
            "required to reset the password and force the role of an "
            "existing account"
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    email = (ADMIN_BOOTSTRAP_EMAIL or "").strip()
    password = ADMIN_BOOTSTRAP_PASSWORD or ""

    if not email:
        return _fail("ADMIN_BOOTSTRAP_EMAIL is not set.")

    if len(password) < MIN_PASSWORD_LENGTH:
        return _fail(
            f"ADMIN_BOOTSTRAP_PASSWORD must be at least "
            f"{MIN_PASSWORD_LENGTH} characters."
        )

    seed_otp_pepper = os.getenv("EDUSHIELD_OTP_PEPPER")
    if not seed_otp_pepper:
        return _fail("EDUSHIELD_OTP_PEPPER is not set.")

    connection = mysql.connector.connect(**DB_CONFIG)
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT user_id FROM users WHERE email = %s",
            (email,)
        )
        existing = cursor.fetchone()

        if existing and not args.update_existing:
            connection.rollback()
            return _fail(
                f"account already exists ({existing['user_id']}); "
                "refusing to change it without --update-existing."
            )

        password_hash = hash_password(password)

        if existing:
            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    role = 'admin',
                    account_status = 'active'
                WHERE user_id = %s
                """,
                (password_hash, existing["user_id"])
            )
            action = f"updated existing account {existing['user_id']}"
        else:
            user_id = "ADM" + secrets.token_hex(4).upper()
            cursor.execute(
                """
                INSERT INTO users
                (
                    user_id, name, email, institutional_email,
                    external_id, role, phone_number, account_status,
                    password_hash
                )
                VALUES
                (%s, %s, %s, %s, %s, 'admin', '', 'active', %s)
                """,
                (
                    user_id,
                    "Administrator",
                    email,
                    email,
                    user_id,
                    password_hash,
                )
            )
            action = f"created admin {user_id}"

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    print(f"create_admin: {action} ({email}). Password not shown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
