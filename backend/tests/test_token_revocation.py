"""
Regression tests for the persistent JWT revocation store.

Revocation used to live in an in-process set: it was lost on restart
and was invisible to the other workers of a multi-process server. The
revocation now lives in the database (revoked_tokens).

These tests prove that:

    * a token works before it is revoked,
    * a token fails after it is revoked,
    * a revoked token stays revoked after a simulated restart,
    * an expired token stays invalid,
    * another user's token is unaffected,
    * expired revocation rows are cleaned up safely.

These run against a real MySQL database (edushield_test). See
tests/dbtest.py for the safety guard and fixture helpers.

Run from backend/:
    python -m unittest discover -s tests -v
"""

import datetime
import importlib
import os
import sys
import unittest
import uuid
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test configuration must be set before the app is imported.
os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"
os.environ["EDUSHIELD_SMS_PROVIDER"] = "disabled"
os.environ["EDUSHIELD_ENV"] = "test"
os.environ["OTP_DELIVERY_MODE"] = "demo"

import jwt  # noqa: E402

import app as backend  # noqa: E402
import auth as auth_module  # noqa: E402
import revocation  # noqa: E402
from auth import generate_token  # noqa: E402
from config import JWT_SECRET  # noqa: E402
from dbtest import (  # noqa: E402
    RealDatabaseTestCase,
    add_user,
    connect,
    fresh_fetch_all,
)


STUDENT = "S1024"
OTHER_STUDENT = "S1025"


class RevocationBase(RealDatabaseTestCase):

    seed_default_fixtures = True

    def seed(self):
        add_user(
            self.connection,
            user_id=STUDENT, name="Rahul", email="rahul@student.test",
            phone_number="9000000001", role="student", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=OTHER_STUDENT, name="Bilal", email="bilal@student.test",
            phone_number="9000000002", role="student", password_hash="x",
        )

    def after_setup(self):
        backend.limiter.reset()

        patches = [
            mock.patch.object(
                backend, "get_db",
                side_effect=lambda: connect(self.db_config),
            ),
            mock.patch.object(backend, "send_email", return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.client = backend.app.test_client()

    # --- helpers --------------------------------------------------
    def headers(self, user_id=STUDENT, role="student"):
        return {
            "Authorization": "Bearer " + generate_token(user_id, role)
        }

    def token_for(self, user_id=STUDENT, role="student"):
        return generate_token(user_id, role)

    def expired_token(self, user_id=STUDENT, role="student"):
        """A token whose expiry is already in the past."""

        now = datetime.datetime.now(datetime.timezone.utc)

        payload = {
            "user_id": user_id,
            "role": role,
            "jti": uuid.uuid4().hex,
            "iat": now - datetime.timedelta(minutes=120),
            "exp": now - datetime.timedelta(minutes=60),
        }

        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    def me(self, headers, client=None):
        return (client or self.client).get("/api/auth/me", headers=headers)

    def revocation_rows(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM revoked_tokens ORDER BY revocation_id",
        )

    def logout(self, headers, client=None):
        return (client or self.client).post(
            "/api/auth/logout", headers=headers
        )


class TokenRevocationTests(RevocationBase):

    def test_token_works_before_revocation(self):
        headers = self.headers()

        resp = self.me(headers)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["user"]["user_id"], STUDENT)

        # Nothing is recorded yet.
        self.assertEqual(self.revocation_rows(), [])

    def test_token_fails_after_revocation(self):
        headers = self.headers()

        self.assertEqual(self.me(headers).status_code, 200)

        resp = self.logout(headers)
        self.assertEqual(resp.status_code, 200)

        # The token is refused from now on.
        resp = self.me(headers)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(
            resp.get_json()["message"], "Invalid or expired token"
        )

        # The revocation is durable: it is in the database with the
        # token identifier, the owner, both timestamps and a reason.
        rows = self.revocation_rows()
        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertEqual(row["user_id"], STUDENT)
        self.assertIsNotNone(row["revoked_at"])
        self.assertIsNotNone(row["expires_at"])
        self.assertEqual(row["reason"], "logout")
        self.assertTrue(row["jti"])

        # No raw token is stored, only its identifier.
        stored = " ".join(str(value) for value in row.values())
        self.assertNotIn(headers["Authorization"].split(" ", 1)[1], stored)

    def test_revoking_a_token_twice_is_safe(self):
        headers = self.headers()

        self.assertEqual(self.logout(headers).status_code, 200)

        # The token is already refused, so a second logout is refused
        # too, and nothing is duplicated.
        self.assertEqual(self.logout(headers).status_code, 401)
        self.assertEqual(len(self.revocation_rows()), 1)

    def test_token_remains_revoked_after_simulated_restart(self):
        headers = self.headers()

        self.assertEqual(self.me(headers).status_code, 200)
        self.assertEqual(self.logout(headers).status_code, 200)

        # Simulate an application restart: reload the auth module so
        # every in-process cache is thrown away, and use a brand-new
        # test client.
        importlib.reload(auth_module)

        client = backend.app.test_client()

        resp = self.me(headers, client=client)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(
            resp.get_json()["message"], "Invalid or expired token"
        )

        # The revocation is still in the database.
        self.assertEqual(len(self.revocation_rows()), 1)

    def test_expired_token_remains_invalid(self):
        headers = {
            "Authorization": "Bearer " + self.expired_token()
        }

        resp = self.me(headers)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(
            resp.get_json()["message"], "Invalid or expired token"
        )

        # An expired token is refused by the expiry check, before the
        # revocation store is even consulted.
        self.assertEqual(self.revocation_rows(), [])

    def test_expired_token_is_refused_even_when_it_is_revoked(self):
        token = self.expired_token()
        headers = {"Authorization": "Bearer " + token}

        payload = auth_module.decode_token(token)

        # The token is already expired, so it cannot even be revoked
        # through the API. It stays invalid either way.
        self.assertIsNone(payload)
        self.assertEqual(self.me(headers).status_code, 401)

    def test_another_users_token_is_unaffected(self):
        student_headers = self.headers(STUDENT)
        other_headers = self.headers(OTHER_STUDENT)

        self.assertEqual(self.logout(student_headers).status_code, 200)

        # The revoked token is refused.
        self.assertEqual(self.me(student_headers).status_code, 401)

        # The other user's token still works.
        resp = self.me(other_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["user"]["user_id"], OTHER_STUDENT)

        # Exactly one row was written, and it belongs to the user who
        # logged out.
        rows = self.revocation_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], STUDENT)

    def test_revocation_is_unique_per_token(self):
        first = self.headers()
        second = self.headers()

        self.logout(first)
        self.logout(second)

        rows = self.revocation_rows()

        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["jti"] for row in rows}), 2)

    def test_expired_revocation_rows_are_cleaned_up(self):
        expired_headers = self.headers()
        live_headers = self.headers()

        self.assertEqual(self.logout(expired_headers).status_code, 200)
        self.assertEqual(self.logout(live_headers).status_code, 200)
        self.assertEqual(len(self.revocation_rows()), 2)

        # Age the first row past its token expiry, the way a row that
        # outlived its token would look.
        expired_jti = self.revocation_rows()[0]["jti"]
        cursor = self.connection.cursor()
        cursor.execute(
            """
            UPDATE revoked_tokens
            SET expires_at = TIMESTAMPADD(MINUTE, -5, NOW())
            WHERE jti = %s
            """,
            (expired_jti,),
        )
        self.connection.commit()

        removed = revocation.cleanup_expired()

        self.assertEqual(removed, 1)

        rows = self.revocation_rows()
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["jti"], expired_jti)

        # Cleaning up an expired row never un-revokes a live token.
        self.assertEqual(self.me(live_headers).status_code, 401)


if __name__ == "__main__":
    unittest.main()
