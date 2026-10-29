"""
Regression tests for the AI assessment / parent verification split.

Before the fix the AI assessment ran inside the same transaction as the
parent OTP verification. A failing model therefore rolled the whole
transaction back and undid a successful parent verification.

These tests prove that:

    * a successful dual OTP verification survives an AI failure,
    * an AI failure can never enable a mentor approval,
    * a successful retry creates a valid assessment,
    * a request without the required assessment cannot be approved,
    * repeated retries do not duplicate records or corrupt the request.

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

# Test configuration must be set before the app is imported.
os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"
os.environ["EDUSHIELD_SMS_PROVIDER"] = "disabled"
os.environ["EDUSHIELD_ENV"] = "test"
os.environ["OTP_DELIVERY_MODE"] = "demo"

import app as backend  # noqa: E402
from auth import generate_token  # noqa: E402
from dbtest import (  # noqa: E402
    RealDatabaseTestCase,
    add_assignment,
    add_user,
    connect,
    fresh_fetch_all,
    fresh_fetch_one,
)


STUDENT = "S1024"
MENTOR = "M021"
ADMIN = "A001"
NEW_PHONE = "9555666777"


class AiIsolationBase(RealDatabaseTestCase):

    seed_default_fixtures = True

    def seed(self):
        add_user(
            self.connection,
            user_id=STUDENT, name="Rahul", email="rahul@student.test",
            parent_email="parent@example.test", parent_phone="+919876504821",
            phone_number="9000000001", role="student", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=MENTOR, name="Dr. Harsha", email="harsha@mentor.test",
            phone_number="9000000002", role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=ADMIN, name="Admin", email="admin@test",
            phone_number="9000000003", role="admin", password_hash="x",
        )

        add_assignment(self.connection, STUDENT, MENTOR)

    def after_setup(self):
        backend.limiter.reset()

        self.sent_sms = []
        self.sent_email = []

        patches = [
            mock.patch.object(
                backend, "get_db",
                side_effect=lambda: connect(self.db_config),
            ),
            mock.patch.object(
                backend, "send_sms", side_effect=self._capture_sms,
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
        self.student_auth = {
            "Authorization": "Bearer " + generate_token(STUDENT, "student"),
            "X-Device-ID": "device-1",
        }
        self.mentor_auth = {
            "Authorization": "Bearer " + generate_token(MENTOR, "mentor"),
            "X-Device-ID": "device-m",
        }
        self.admin_auth = {
            "Authorization": "Bearer " + generate_token(ADMIN, "admin"),
        }

    # Capture outbound messages instead of sending them.
    def _capture_sms(self, to, text, **kwargs):
        self.sent_sms.append((to, text))

    def _capture_email(self, to, subject, body, html=None, **kwargs):
        self.sent_email.append((to, subject, body))

    # --- helpers --------------------------------------------------
    def break_the_model(self):
        """
        Make the AI assessment fail the way a broken model would.

        Returns the patcher so the test can put the model back.
        """

        patcher = mock.patch.object(
            backend,
            "run_ai_assessment",
            side_effect=RuntimeError("model artifact unavailable"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        return patcher

    def restore_the_model(self, patcher):
        patcher.stop()

    def submit_request(self, new_phone=NEW_PHONE):
        return self.client.post(
            "/api/phone-change-requests",
            json={"new_phone": new_phone},
            headers=self.student_auth,
        )

    def sms_code(self):
        text = self.sent_sms[-1][1]
        return re.search(r"code is (\d{6})", text).group(1)

    def _parent_email_body(self):
        bodies = [
            b for to, _, b in self.sent_email if to == "parent@example.test"
        ]
        return bodies[-1]

    def email_code(self):
        body = self._parent_email_body()
        return re.search(r"verification code: (\d{6})", body).group(1)

    def parent_token(self):
        body = self._parent_email_body()
        return re.search(r"/parent/verify/([A-Za-z0-9_\-]+)", body).group(1)

    def verify(self, token, channel, code):
        return self.client.post(
            f"/parent/verify/{token}/{channel}",
            json={"code": code},
        )

    def verify_both_channels(self):
        """Run the whole parent flow and return the two responses."""

        self.submit_request()
        token = self.parent_token()

        sms = self.verify(token, "SMS", self.sms_code())
        email = self.verify(token, "EMAIL", self.email_code())

        return sms, email

    def request_id(self):
        return self.requests()[0]["request_id"]

    def requests(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM phone_change_requests ORDER BY request_id",
        )

    def request_row(self):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM phone_change_requests WHERE request_id = %s",
            (self.request_id(),),
        )

    def otp_rows(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM phone_change_otps ORDER BY otp_id",
        )

    def user(self, user_id):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM users WHERE user_id = %s",
            (user_id,),
        )

    def ai_rows(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM ai_assessments WHERE request_id = %s",
            (self.request_id(),),
        )

    def ai_state(self):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM ai_assessment_status WHERE request_id = %s",
            (self.request_id(),),
        )

    def prediction_rows(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM model_predictions WHERE request_id = %s",
            (self.request_id(),),
        )

    def timeline_rows(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM request_timeline WHERE request_id = %s "
            "ORDER BY timeline_id",
            (self.request_id(),),
        )

    def alert_rows(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM security_alerts WHERE request_id = %s",
            (self.request_id(),),
        )

    def audit_actions(self):
        return [
            r["action"]
            for r in fresh_fetch_all(
                self.db_config, "SELECT action FROM audit_logs"
            )
        ]

    def notifications(self, user_id=None):
        if user_id is None:
            return fresh_fetch_all(
                self.db_config,
                "SELECT * FROM notifications ORDER BY notification_id",
            )

        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM notifications WHERE user_id = %s "
            "ORDER BY notification_id",
            (user_id,),
        )

    def approve(self):
        return self.client.patch(
            f"/api/phone-change-requests/{self.request_id()}",
            json={"decision": "APPROVED"},
            headers=self.mentor_auth,
        )

    def retry(self, headers=None):
        return self.client.post(
            f"/api/admin/ai-assessments/{self.request_id()}/retry",
            headers=headers if headers is not None else self.admin_auth,
        )


class AiFailureIsolationTests(AiIsolationBase):

    def test_successful_dual_otp_verification_survives_an_ai_failure(self):
        self.break_the_model()

        sms, email = self.verify_both_channels()

        # Both codes were accepted: the parent is not asked to retry.
        self.assertEqual(sms.status_code, 200)
        self.assertEqual(email.status_code, 200)
        self.assertEqual(email.get_json()["auth_status"], "VERIFIED")

        # The verification is durable: it was NOT rolled back with the
        # failed assessment.
        row = self.request_row()
        self.assertEqual(row["auth_status"], "VERIFIED")
        self.assertEqual(row["parent_verification_status"], "VERIFIED")
        self.assertIsNotNone(row["parent_verified_at"])

        otps = {o["channel"]: o for o in self.otp_rows()}
        self.assertEqual(otps["SMS"]["verified"], 1)
        self.assertEqual(otps["EMAIL"]["verified"], 1)
        self.assertIsNotNone(otps["SMS"]["verified_at"])
        self.assertIsNotNone(otps["EMAIL"]["verified_at"])

        # The failure is recorded, not swallowed.
        state = self.ai_state()
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "FAILED")
        self.assertIn("model artifact unavailable", state["last_error"])
        self.assertEqual(state["attempts"], 1)

        actions = self.audit_actions()
        self.assertIn("PARENT_AUTHENTICATION_COMPLETED", actions)
        self.assertIn("AI_ASSESSMENT_FAILED", actions)

        # No assessment was stored (the model never got that far).
        self.assertEqual(self.ai_rows(), [])

        # The mentor was told that the assessment is unavailable.
        types = [n["type"] for n in self.notifications(MENTOR)]
        self.assertIn("AI_ASSESSMENT_UNAVAILABLE", types)

        mentor_mails = [s for to, s, _ in self.sent_email
                        if to == "harsha@mentor.test"]
        self.assertTrue(
            any("assessment" in s.lower() for s in mentor_mails),
            "the mentor must be told that the assessment is unavailable"
        )

    def test_ai_failure_cannot_enable_mentor_approval(self):
        self.break_the_model()

        self.verify_both_channels()

        self.assertEqual(self.ai_state()["status"], "FAILED")

        resp = self.approve()

        self.assertEqual(resp.status_code, 403)
        self.assertIn("assessment", resp.get_json()["message"].lower())

        # Nothing about the request changed.
        self.assertEqual(self.request_row()["status"], "PENDING")
        self.assertEqual(self.user(STUDENT)["phone_number"], "9000000001")

    def test_ai_failure_never_lets_a_mentor_approve_by_accident(self):
        """
        The gate is on the assessment, not on the AI having run.

        Even with a healthy model, a request whose assessment is gone
        cannot be approved.
        """

        self.verify_both_channels()

        self.assertEqual(self.ai_state()["status"], "COMPLETED")
        self.assertEqual(len(self.ai_rows()), 1)

        cursor = self.connection.cursor()
        cursor.execute(
            "DELETE FROM ai_assessments WHERE request_id = %s",
            (self.request_id(),),
        )
        cursor.execute(
            "DELETE FROM ai_assessment_status WHERE request_id = %s",
            (self.request_id(),),
        )
        self.connection.commit()
        cursor.close()

        resp = self.approve()

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.user(STUDENT)["phone_number"], "9000000001")


class AiRetryTests(AiIsolationBase):

    def test_successful_retry_creates_a_valid_assessment(self):
        patcher = self.break_the_model()

        self.verify_both_channels()

        self.assertEqual(self.ai_state()["status"], "FAILED")
        self.assertEqual(self.ai_rows(), [])

        # The model comes back and an admin retries the assessment.
        self.restore_the_model(patcher)

        resp = self.retry()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["ai_assessment_status"], "COMPLETED")

        state = self.ai_state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertIsNone(state["last_error"])
        self.assertIsNotNone(state["completed_at"])

        rows = self.ai_rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["risk_score"])
        self.assertIn(rows[0]["risk_level"], ("LOW", "MEDIUM", "HIGH"))
        self.assertIsNotNone(rows[0]["model_version"])

        # The request is reviewable again.
        self.assertEqual(self.approve().status_code, 200)
        self.assertEqual(self.user(STUDENT)["phone_number"], NEW_PHONE)

    def test_repeated_retries_do_not_duplicate_records(self):
        patcher = self.break_the_model()

        self.verify_both_channels()

        self.assertEqual(self.ai_state()["status"], "FAILED")

        self.restore_the_model(patcher)

        for _ in range(3):
            resp = self.retry()
            self.assertEqual(resp.status_code, 200)

        # One assessment, one monitoring record, one alert.
        self.assertEqual(len(self.ai_rows()), 1)
        self.assertEqual(len(self.prediction_rows()), 1)
        self.assertLessEqual(len(self.alert_rows()), 1)

        # One timeline entry for the assessment itself.
        assessed = [
            e for e in self.timeline_rows()
            if e["event_type"] == "AI_ASSESSED"
        ]
        self.assertEqual(len(assessed), 1)

        # The audit trail records every attempt exactly once.
        actions = self.audit_actions()
        self.assertEqual(actions.count("AI_ASSESSMENT_GENERATED"), 1)
        self.assertEqual(actions.count("AI_ASSESSMENT_FAILED"), 1)

        state = self.ai_state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertGreaterEqual(state["attempts"], 3)

        # The request itself is untouched by the retries.
        row = self.request_row()
        self.assertEqual(row["auth_status"], "VERIFIED")
        self.assertEqual(row["status"], "PENDING")

    def test_retry_of_a_healthy_assessment_is_safe(self):
        self.verify_both_channels()

        self.assertEqual(self.ai_state()["status"], "COMPLETED")

        resp = self.retry()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.ai_rows()), 1)

    def test_only_an_admin_can_trigger_a_retry(self):
        self.break_the_model()

        self.verify_both_channels()

        resp = self.retry(headers=self.mentor_auth)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.ai_state()["status"], "FAILED")

    def test_retry_of_an_unknown_request_is_404(self):
        resp = self.client.post(
            "/api/admin/ai-assessments/REQ_DOES_NOT_EXIST/retry",
            headers=self.admin_auth,
        )

        self.assertEqual(resp.status_code, 404)

    def test_retry_is_refused_before_parent_verification(self):
        self.submit_request()

        resp = self.retry()

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.ai_state(), None)


if __name__ == "__main__":
    unittest.main()
