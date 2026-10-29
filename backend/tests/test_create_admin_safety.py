"""The bootstrap admin script must not silently change existing accounts."""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))

import create_admin  # noqa: E402


EMAIL = "admin@example.test"
PASSWORD = "a-long-test-password"


class FakeCursor:
    def __init__(self, existing):
        self.existing = existing
        self.statements = []
        self.closed = False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.existing

    def close(self):
        self.closed = True

    def updates(self):
        return [
            statement
            for statement, _ in self.statements
            if "UPDATE users" in statement
        ]

    def inserts(self):
        return [
            statement
            for statement, _ in self.statements
            if "INSERT INTO users" in statement
        ]


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, dictionary=False):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class CreateAdminSafetyTests(unittest.TestCase):

    def run_main(self, argv, existing):
        cursor = FakeCursor(existing)
        connection = FakeConnection(cursor)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.dict(
            os.environ, {"EDUSHIELD_OTP_PEPPER": "test-pepper"}
        ), mock.patch.object(
            create_admin, "ADMIN_BOOTSTRAP_EMAIL", EMAIL
        ), mock.patch.object(
            create_admin, "ADMIN_BOOTSTRAP_PASSWORD", PASSWORD
        ), mock.patch.object(
            create_admin, "DB_CONFIG", {}
        ), mock.patch.object(
            create_admin, "hash_password", return_value="hashed"
        ), mock.patch.object(
            create_admin.mysql.connector, "connect", return_value=connection
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = create_admin.main(argv)

        return result, stdout.getvalue(), stderr.getvalue(), cursor

    def test_existing_account_is_refused_without_flag(self):
        result, stdout, stderr, cursor = self.run_main(
            [], {"user_id": "ADM1"}
        )

        self.assertEqual(result, 1)
        self.assertIn("--update-existing", stderr)
        self.assertEqual(cursor.updates(), [])
        self.assertNotIn(PASSWORD, stdout + stderr)

    def test_existing_account_is_updated_only_with_flag(self):
        result, stdout, stderr, cursor = self.run_main(
            ["--update-existing"], {"user_id": "ADM1"}
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(cursor.updates()), 1)
        self.assertNotIn(PASSWORD, stdout + stderr)

    def test_new_account_is_created_without_flag(self):
        result, stdout, stderr, cursor = self.run_main([], None)

        self.assertEqual(result, 0)
        self.assertEqual(len(cursor.inserts()), 1)
        self.assertEqual(cursor.updates(), [])
        self.assertNotIn(PASSWORD, stdout + stderr)

    def test_flag_defaults_to_false(self):
        self.assertFalse(create_admin.parse_args([]).update_existing)
        self.assertTrue(
            create_admin.parse_args(["--update-existing"]).update_existing
        )


if __name__ == "__main__":
    unittest.main()
