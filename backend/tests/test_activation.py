"""
Tests for account activation (Phase 1).

These run against a real MySQL database (edushield_test). See
tests/dbtest.py for the safety guard and fixture helpers.

Run from backend/:
    python -m unittest discover -s tests -v
"""

import os
import re
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"
os.environ["EDUSHIELD_SMS_PROVIDER"] = "disabled"
os.environ["EDUSHIELD_ENV"] = "test"
os.environ["OTP_DELIVERY_MODE"] = "demo"

import app as backend  # noqa: E402
from auth import hash_password, verify_password  # noqa: E402
from dbtest import (  # noqa: E402
    RealDatabaseTestCase,
    add_user,
    connect,
    fresh_fetch_all,
    fresh_fetch_one,
    shift_time,
)
from sis_import import UNUSABLE_PASSWORD_HASH  # noqa: E402


STUDENT = "24STUCHH010221"
EMAIL = "asha@univ.test"


class ActivationBase(RealDatabaseTestCase):

    def seed(self):
        add_user(
            self.connection,
            user_id=STUDENT, name="Asha", email=EMAIL,
            parent_email=None, parent_phone=None,
            phone_number="9000000001", role="student",
            password_hash=UNUSABLE_PASSWORD_HASH,
            account_status="pending_activation",
        )

    def after_setup(self):
        backend.limiter.reset()
        self.sent_email = []

        patches = [
            mock.patch.object(
                backend, "get_db",
                side_effect=lambda: connect(self.db_config),
            ),
            mock.patch.object(
                backend, "send_email", side_effect=self._capture_email,
            ),
            mock.patch.object(
                backend, "get_client_location", return_value=(12.97, 77.59),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.client = backend.app.test_client()

    def _capture_email(self, to, subject, body, html=None, **kwargs):
        self.sent_email.append((to, subject, body))

    def user(self):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM users WHERE user_id = %s",
            (STUDENT,),
        )

    def activation_otps(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM account_activation_otps "
            "WHERE user_id = %s ORDER BY id",
            (STUDENT,),
        )

    def set_account_status(self, status):
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE users SET account_status = %s WHERE user_id = %s",
            (status, STUDENT),
        )
        self.connection.commit()
        cursor.close()

    def set_password_hash(self, password_hash):
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s",
            (password_hash, STUDENT),
        )
        self.connection.commit()
        cursor.close()

    def request_code(self, external_id=STUDENT):
        return self.client.post(
            "/api/auth/activate/request",
            json={"external_id": external_id},
        )

    def code(self):
        body = self.sent_email[-1][2]
        return re.search(r"(\d{6})", body).group(1)

    def verify(self, code, password="secretpass123", confirm=None,
               external_id=STUDENT):
        payload = {
            "external_id": external_id,
            "code": code,
            "password": password,
        }
        if confirm is not None:
            payload["confirm_password"] = confirm
        return self.client.post("/api/auth/activate/verify", json=payload)


class ActivationRequestTests(ActivationBase):

    def test_request_emails_code_to_institutional_address(self):
        resp = self.request_code()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.sent_email), 1)
        self.assertEqual(self.sent_email[0][0], EMAIL)
        self.assertRegex(self.code(), r"^\d{6}$")

    def test_only_a_keyed_hash_is_stored_never_the_code(self):
        self.request_code()
        code = self.code()

        stored = self.activation_otps()[-1]["code_hash"]
        self.assertNotEqual(stored, code)
        self.assertNotIn(code, str(stored))
        self.assertEqual(len(stored), 64)

    def test_unknown_id_gets_generic_reply_and_no_email(self):
        resp = self.request_code(external_id="nobody")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.sent_email, [])
        self.assertIn("pending account", resp.get_json()["message"])

    def test_active_account_gets_generic_reply_and_no_email(self):
        self.set_account_status("active")
        resp = self.request_code()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.sent_email, [])

    def test_resend_cooldown_blocks_an_immediate_second_email(self):
        self.request_code()
        self.request_code()
        self.assertEqual(len(self.sent_email), 1)

        shift_time(self.connection, 61)
        self.request_code()
        self.assertEqual(len(self.sent_email), 2)


class ActivationVerifyTests(ActivationBase):

    def test_correct_code_activates_and_sets_password(self):
        self.request_code()
        resp = self.verify(self.code())
        self.assertEqual(resp.status_code, 200)

        user = self.user()
        self.assertEqual(user["account_status"], "active")
        self.assertTrue(verify_password("secretpass123", user["password_hash"]))
        self.assertEqual(self.activation_otps()[-1]["used"], 1)

    def test_activated_user_can_log_in(self):
        self.request_code()
        self.verify(self.code())

        resp = self.client.post(
            "/api/auth/login",
            json={"email": EMAIL, "password": "secretpass123"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["user"]["user_id"], STUDENT)

    def test_pending_user_cannot_log_in_even_with_password(self):
        self.set_password_hash(hash_password("known"))

        resp = self.client.post(
            "/api/auth/login",
            json={"email": EMAIL, "password": "known"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_wrong_code_counts_attempts_and_locks_at_three(self):
        self.request_code()
        wrong = "000000" if self.code() != "000000" else "111111"

        r1 = self.verify(wrong)
        self.assertEqual(r1.status_code, 401)
        self.assertEqual(r1.get_json()["attempts_left"], 2)

        self.verify(wrong)
        r3 = self.verify(wrong)
        self.assertEqual(r3.status_code, 423)

        # Even the correct code is refused once locked.
        self.assertEqual(self.verify(self.code()).status_code, 423)
        self.assertEqual(self.user()["account_status"], "pending_activation")

    def test_expired_code_is_rejected(self):
        self.request_code()
        shift_time(self.connection, 6 * 60)
        self.assertEqual(self.verify(self.code()).status_code, 410)

    def test_malformed_code_is_rejected(self):
        self.request_code()
        self.assertEqual(self.verify("12ab").status_code, 400)

    def test_short_password_is_rejected_without_consuming_code(self):
        self.request_code()
        resp = self.verify(self.code(), password="short")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.activation_otps()[-1]["used"], 0)

    def test_password_mismatch_is_rejected(self):
        self.request_code()
        resp = self.verify(self.code(), password="secretpass123",
                           confirm="different123")
        self.assertEqual(resp.status_code, 400)

    def test_verify_for_unknown_id_is_not_found(self):
        self.assertEqual(
            self.verify("123456", external_id="nobody").status_code, 404
        )

    def test_code_cannot_be_reused_after_activation(self):
        self.request_code()
        code = self.code()
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).status_code, 404)


if __name__ == "__main__":
    unittest.main()
