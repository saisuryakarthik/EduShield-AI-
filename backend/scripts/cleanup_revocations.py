"""
Remove expired token revocations from the database.

A revocation row is only useful while its token could still be used.
Once the token's own expiry has passed, the row is dead weight: the
token is refused by the expiry check before the revocation store is
even consulted.

Usage (from backend/, with the venv active):

    python scripts/cleanup_revocations.py

Safe to run at any time and as often as you like. It only deletes rows
whose expiry has already passed.
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import revocation  # noqa: E402


def main():
    removed = revocation.cleanup_expired()

    print(f"cleanup_revocations: removed {removed} expired revocation(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
