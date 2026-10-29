"""
End-to-end tests for the dual-OTP phone-change flow.

These run against a real MySQL database (edushield_test). See
tests/dbtest.py for the safety guard and fixture helpers.

Run from backend/:
    python -m unittest discover -s tests -v
"""

import os
import re
import sys
import threading
import time
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

import otp  # noqa: E402
import app as backend  # noqa: E402
from auth import generate_token, hash_password  # noqa: E402
from dbtest import (  # noqa: E402
    RealDatabaseTestCase,
    add_assignment,
    add_user,
    connect,
    fresh_fetch_all,
    fresh_fetch_one,
    shift_time,
)


STUDENT = "S1024"
MENTOR = "M021"
NEW_PHONE = "9555666777"


class FlowTestBase(RealDatabaseTestCase):

    # Fixtures are seeded via seed(); disable the default hook body.
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

        # Mentor authorisation now comes from the assignment table.
        add_assignment(self.connection, STUDENT, MENTOR)

    def after_setup(self):
        # Rate-limit state is process-wide; clear it so tests do not
        # bleed into one another (they reuse the same user IDs).
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

    # Capture outbound messages instead of sending them.
    def _capture_sms(self, to, text, **kwargs):
        self.sent_sms.append((to, text))

    def _capture_email(self, to, subject, body, html=None, **kwargs):
        self.sent_email.append((to, subject, body))

    # --- DB readers (replaces the old in-memory state) -------------
    def otps(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM phone_change_otps ORDER BY otp_id",
        )

    def requests(self):
        return fresh_fetch_all(
            self.db_config,
            "SELECT * FROM phone_change_requests ORDER BY request_id",
        )

    def user(self, user_id):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM users WHERE user_id = %s",
            (user_id,),
        )

    def ai_rows(self):
        return fresh_fetch_all(
            self.db_config, "SELECT * FROM ai_assessments"
        )

    def audit_actions(self):
        return [
            r["action"]
            for r in fresh_fetch_all(
                self.db_config, "SELECT action FROM audit_logs"
            )
        ]

    # --- helpers --------------------------------------------------
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

    def request_id(self):
        return self.requests()[0]["request_id"]

    def auth_status(self):
        return self.request_id_row()["auth_status"]

    def request_id_row(self):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM phone_change_requests WHERE request_id = %s",
            (self.request_id(),),
        )

    def approve(self):
        return self.client.patch(
            f"/api/phone-change-requests/{self.request_id()}",
            json={"decision": "APPROVED"},
            headers=self.mentor_auth,
        )


class SubmissionTests(FlowTestBase):

    def test_submission_creates_pending_request_and_two_independent_codes(self):
        resp = self.submit_request()
        self.assertEqual(resp.status_code, 201)

        otps = self.otps()
        self.assertEqual(len(otps), 2)
        self.assertEqual({o["channel"] for o in otps}, {"SMS", "EMAIL"})
        self.assertNotEqual(otps[0]["code_hash"], otps[1]["code_hash"])

        self.assertEqual(self.auth_status(), "PENDING")

    def test_codes_are_never_returned_in_api_response_or_stored_plaintext(self):
        resp = self.submit_request()
        sms, email = self.sms_code(), self.email_code()

        self.assertNotIn(sms, resp.get_data(as_text=True))
        self.assertNotIn(email, resp.get_data(as_text=True))

        stored = " ".join(str(o["code_hash"]) for o in self.otps())
        self.assertNotIn(sms, stored)
        self.assertNotIn(email, stored)

    def test_parent_contacts_receive_sms_and_email(self):
        resp = self.submit_request()
        self.assertEqual(resp.get_json()["parent_delivery"],
                         {"sms": True, "email": True})
        self.assertEqual(self.sent_sms[-1][0], "+919876504821")
        self.assertIn("parent@example.test",
                      [to for to, _, _ in self.sent_email])

    def test_mentor_is_notified_of_new_request(self):
        self.submit_request()
        recipients = [to for to, subject, _ in self.sent_email]
        self.assertIn("harsha@mentor.test", recipients)

    def test_second_open_request_is_refused(self):
        self.submit_request()
        resp = self.submit_request(new_phone="9111222333")
        self.assertEqual(resp.status_code, 409)

    def test_no_ai_assessment_before_parent_verification(self):
        self.submit_request()
        self.assertEqual(self.ai_rows(), [])


class MentorGateTests(FlowTestBase):

    def test_mentor_cannot_approve_before_any_verification(self):
        self.submit_request()
        resp = self.approve()
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.user(STUDENT)["phone_number"], "9000000001")

    def test_mentor_cannot_approve_with_only_sms_verified(self):
        self.submit_request()
        token = self.parent_token()
        ok = self.verify(token, "sms", self.sms_code())
        self.assertEqual(ok.status_code, 200)

        self.assertEqual(self.auth_status(), "PENDING")
        self.assertEqual(self.approve().status_code, 403)

    def test_mentor_cannot_approve_with_only_email_verified(self):
        self.submit_request()
        token = self.parent_token()
        ok = self.verify(token, "email", self.email_code())
        self.assertEqual(ok.status_code, 200)

        self.assertEqual(self.auth_status(), "PENDING")
        self.assertEqual(self.approve().status_code, 403)


class DualOtpTests(FlowTestBase):

    def test_both_verified_sets_authentication_verified_and_runs_ai(self):
        self.submit_request()
        token = self.parent_token()

        r1 = self.verify(token, "sms", self.sms_code())
        self.assertEqual(r1.get_json()["auth_status"], "PENDING")

        r2 = self.verify(token, "email", self.email_code())
        self.assertEqual(r2.get_json()["auth_status"], "VERIFIED")

        self.assertEqual(self.auth_status(), "VERIFIED")
        self.assertEqual(
            len(fresh_fetch_all(
                self.db_config,
                "SELECT * FROM ai_assessments WHERE request_id = %s",
                (self.request_id(),),
            )),
            1,
        )
        actions = self.audit_actions()
        self.assertIn("PARENT_AUTHENTICATION_COMPLETED", actions)
        self.assertIn("AI_ASSESSMENT_GENERATED", actions)

    def test_mentor_is_notified_once_when_both_verified(self):
        self.submit_request()
        token = self.parent_token()
        self.verify(token, "sms", self.sms_code())
        self.verify(token, "email", self.email_code())

        mentor_mails = [s for to, s, _ in self.sent_email
                        if to == "harsha@mentor.test"]
        completed = [s for s in mentor_mails if "verification completed" in s]
        self.assertEqual(len(completed), 1)

    def test_approval_succeeds_only_after_both_verified(self):
        self.submit_request()
        token = self.parent_token()
        self.verify(token, "sms", self.sms_code())
        self.verify(token, "email", self.email_code())

        resp = self.approve()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.user(STUDENT)["phone_number"], NEW_PHONE)

    def test_codes_are_one_time_use(self):
        self.submit_request()
        token = self.parent_token()
        code = self.sms_code()
        self.assertEqual(self.verify(token, "sms", code).status_code, 200)
        self.assertEqual(self.verify(token, "sms", code).status_code, 409)

    def test_sms_code_cannot_verify_email_channel(self):
        self.submit_request()
        token = self.parent_token()
        resp = self.verify(token, "email", self.sms_code())
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.auth_status(), "PENDING")

    def test_wrong_code_counts_attempts_and_locks_at_three(self):
        self.submit_request()
        token = self.parent_token()
        wrong = "000000" if self.sms_code() != "000000" else "111111"

        r1 = self.verify(token, "sms", wrong)
        self.assertEqual(r1.status_code, 401)
        self.assertEqual(r1.get_json()["attempts_left"], 2)

        self.verify(token, "sms", wrong)
        r3 = self.verify(token, "sms", wrong)
        self.assertEqual(r3.status_code, 423)

        sms_row = next(o for o in self.otps() if o["channel"] == "SMS")
        self.assertEqual(sms_row["locked"], 1)

        # Even the correct code is refused once locked.
        r4 = self.verify(token, "sms", self.sms_code())
        self.assertEqual(r4.status_code, 423)
        self.assertEqual(self.auth_status(), "PENDING")

    def test_expired_code_is_rejected(self):
        self.submit_request()
        token = self.parent_token()
        code = self.sms_code()

        shift_time(self.connection, 6 * 60)  # OTP TTL is 5 minutes
        resp = self.verify(token, "sms", code)
        self.assertEqual(resp.status_code, 410)

    def test_malformed_code_is_rejected_without_counting(self):
        self.submit_request()
        token = self.parent_token()
        resp = self.verify(token, "sms", "12ab")
        self.assertEqual(resp.status_code, 400)
        sms_row = next(o for o in self.otps() if o["channel"] == "SMS")
        self.assertEqual(sms_row["attempts"], 0)

    def test_unknown_token_is_rejected(self):
        self.submit_request()
        resp = self.verify("not-a-real-token", "sms", "123456")
        self.assertEqual(resp.status_code, 404)

    def test_expired_link_is_rejected(self):
        self.submit_request()
        token = self.parent_token()
        shift_time(self.connection, 16 * 60)  # link TTL is 15 minutes
        resp = self.verify(token, "sms", self.sms_code())
        self.assertEqual(resp.status_code, 410)


class InvalidParentContactTests(FlowTestBase):

    def test_invalid_parent_phone_is_refused_before_anything_is_created(self):
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE users SET parent_phone = %s WHERE user_id = %s",
            ("not-a-number", STUDENT),
        )
        self.connection.commit()
        cursor.close()

        resp = self.submit_request()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.otps(), [])


class SecurityHoldAndCancelTests(FlowTestBase):

    def test_this_wasnt_me_places_hold_and_blocks_approval(self):
        self.submit_request()
        token = self.parent_token()

        resp = self.client.post(f"/parent/report/{token}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.request_id_row()["status"], "SECURITY_HOLD")

        # Codes can no longer be used after the report.
        self.assertEqual(
            self.verify(token, "sms", self.sms_code()).status_code, 409
        )

        self.assertEqual(self.approve().status_code, 403)

    def test_mentor_can_still_reject_a_held_request(self):
        self.submit_request()
        token = self.parent_token()
        self.client.post(f"/parent/report/{token}")

        resp = self.client.patch(
            f"/api/phone-change-requests/{self.request_id()}",
            json={"decision": "REJECTED", "reason": "Reported by parent"},
            headers=self.mentor_auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.user(STUDENT)["phone_number"], "9000000001")

    def test_hold_committed_while_approval_waits_blocks_the_approval(self):
        """
        MySQL row-lock regression test.

        A decision that is already holding the request row commits a
        SECURITY_HOLD. A concurrent approval must wait for that lock and
        then observe the hold, so it cannot approve the request.
        """

        self.submit_request()
        request_id = self.request_id()
        blocker = connect(self.db_config)
        cursor = blocker.cursor()
        outcome = {}

        try:
            blocker.start_transaction()
            cursor.execute(
                "SELECT request_id FROM phone_change_requests "
                "WHERE request_id = %s FOR UPDATE",
                (request_id,),
            )
            self.assertIsNotNone(cursor.fetchone())

            def approve_in_thread():
                client = backend.app.test_client()
                outcome["response"] = client.patch(
                    f"/api/phone-change-requests/{request_id}",
                    json={"decision": "APPROVED"},
                    headers=self.mentor_auth,
                )

            worker = threading.Thread(target=approve_in_thread)
            worker.start()
            time.sleep(0.5)

            self.assertTrue(
                worker.is_alive(),
                "approval did not wait for the request row lock",
            )

            cursor.execute(
                "UPDATE phone_change_requests "
                "SET status = 'SECURITY_HOLD' "
                "WHERE request_id = %s AND status = 'PENDING'",
                (request_id,),
            )
            self.assertEqual(cursor.rowcount, 1)
            blocker.commit()

            worker.join(timeout=15)
            self.assertFalse(worker.is_alive(), "approval did not finish")
        finally:
            try:
                blocker.rollback()
            except Exception:
                pass
            cursor.close()
            blocker.close()

        self.assertEqual(outcome["response"].status_code, 403)
        row = self.request_id_row()
        self.assertEqual(row["status"], "SECURITY_HOLD")
        self.assertEqual(self.user(STUDENT)["phone_number"], "9000000001")

    def test_student_can_cancel_and_codes_stop_working(self):
        self.submit_request()
        token = self.parent_token()
        code = self.sms_code()

        resp = self.client.post(
            f"/api/phone-change-requests/{self.request_id()}/cancel",
            headers=self.student_auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.request_id_row()["status"], "CANCELLED")
        self.assertEqual(self.verify(token, "sms", code).status_code, 409)

    def test_mentor_cannot_cancel_a_students_request(self):
        self.submit_request()
        resp = self.client.post(
            f"/api/phone-change-requests/{self.request_id()}/cancel",
            headers=self.mentor_auth,
        )
        self.assertEqual(resp.status_code, 403)


class ParentPageTests(FlowTestBase):

    def test_parent_page_renders_two_channels_without_leaking_codes(self):
        self.submit_request()
        token = self.parent_token()
        sms, email = self.sms_code(), self.email_code()

        resp = self.client.get(f"/parent/verify/{token}")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('data-channel="SMS"', html)
        self.assertIn('data-channel="EMAIL"', html)
        self.assertNotIn(sms, html)
        self.assertNotIn(email, html)
        self.assertNotIn(self.request_id_row()["old_phone"], html)

    def test_parent_page_shows_invalid_for_unknown_token(self):
        resp = self.client.get("/parent/verify/does-not-exist")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Link not found", resp.get_data(as_text=True))

    def test_parent_page_shows_held_state_after_report(self):
        self.submit_request()
        token = self.parent_token()
        self.client.post(f"/parent/report/{token}")
        # The link stays resolvable so the parent sees the final state.
        resp = self.client.get(f"/parent/verify/{token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Reported and on hold", resp.get_data(as_text=True))


class ResendTests(FlowTestBase):

    def resend(self, token):
        return self.client.post(f"/parent/resend/{token}")

    def test_resend_issues_new_code_and_old_code_stops_working(self):
        self.submit_request()
        token = self.parent_token()
        old_code = self.sms_code()

        shift_time(self.connection, 6 * 60)  # original code has expired

        resp = self.resend(token)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SMS", resp.get_json()["resent"])

        new_code = self.sms_code()

        # The stale code is rejected; the fresh one works.
        self.assertEqual(self.verify(token, "sms", old_code).status_code, 401)
        self.assertEqual(self.verify(token, "sms", new_code).status_code, 200)

    def test_resend_refuses_when_both_channels_verified(self):
        self.submit_request()
        token = self.parent_token()
        self.verify(token, "sms", self.sms_code())
        self.verify(token, "email", self.email_code())

        resp = self.resend(token)
        self.assertEqual(resp.status_code, 409)

    def test_resend_refuses_expired_link(self):
        self.submit_request()
        token = self.parent_token()

        shift_time(self.connection, 16 * 60)  # parent link TTL is 15 minutes
        resp = self.resend(token)
        self.assertEqual(resp.status_code, 410)

    def test_resend_leaves_verified_channel_untouched(self):
        self.submit_request()
        token = self.parent_token()
        self.verify(token, "sms", self.sms_code())

        resp = self.resend(token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["resent"], ["EMAIL"])

        sms_row = next(o for o in self.otps() if o["channel"] == "SMS")
        self.assertEqual(sms_row["verified"], 1)


class SecurityHardeningTests(FlowTestBase):

    def test_login_is_rate_limited_per_account(self):
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE user_id = %s",
            (hash_password("right"), STUDENT),
        )
        self.connection.commit()
        cursor.close()

        for _ in range(10):
            resp = self.client.post(
                "/api/auth/login",
                json={"email": "rahul@student.test", "password": "wrong"},
            )
            self.assertEqual(resp.status_code, 401)

        resp = self.client.post(
            "/api/auth/login",
            json={"email": "rahul@student.test", "password": "wrong"},
        )
        self.assertEqual(resp.status_code, 429)

    def test_db_test_requires_authentication(self):
        resp = self.client.get("/api/db-test")
        self.assertEqual(resp.status_code, 401)

    def test_db_test_is_hidden_in_production(self):
        with mock.patch.dict(os.environ, {"EDUSHIELD_ENV": "production"}):
            resp = self.client.get("/api/db-test", headers=self.student_auth)
        self.assertEqual(resp.status_code, 404)

    def test_logout_revokes_token(self):
        resp = self.client.post("/api/auth/logout", headers=self.student_auth)
        self.assertEqual(resp.status_code, 200)

        me = self.client.get("/api/auth/me", headers=self.student_auth)
        self.assertEqual(me.status_code, 401)


class SecretHandlingTests(unittest.TestCase):

    def test_otp_hash_is_bound_to_request_and_channel(self):
        h = otp.hash_otp("REQ1", "SMS", "123456")
        self.assertTrue(otp.otp_matches("REQ1", "SMS", "123456", h))
        self.assertFalse(otp.otp_matches("REQ2", "SMS", "123456", h))
        self.assertFalse(otp.otp_matches("REQ1", "EMAIL", "123456", h))

    def test_generated_codes_are_six_digits(self):
        for _ in range(200):
            code = otp.generate_otp()
            self.assertRegex(code, r"^\d{6}$")

    def test_startup_fails_without_pepper(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDUSHIELD_OTP_PEPPER", None)
            with self.assertRaises(RuntimeError):
                otp.get_otp_pepper()
        os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"


class AuthStatusRuleTests(unittest.TestCase):

    def test_only_both_verified_is_verified(self):
        self.assertEqual(otp.compute_auth_status(True, True), "VERIFIED")
        self.assertEqual(otp.compute_auth_status(True, False), "PENDING")
        self.assertEqual(otp.compute_auth_status(False, True), "PENDING")
        self.assertEqual(otp.compute_auth_status(False, False), "PENDING")


class PhoneNormalisationTests(unittest.TestCase):

    def test_ten_digit_indian_number_gets_country_code(self):
        self.assertEqual(otp.normalize_phone_e164("9876504821"), "+919876504821")

    def test_already_e164_is_kept(self):
        self.assertEqual(otp.normalize_phone_e164("+14155550100"), "+14155550100")

    def test_garbage_is_rejected(self):
        self.assertIsNone(otp.normalize_phone_e164("12ab"))
        self.assertIsNone(otp.normalize_phone_e164(""))

    def test_masking(self):
        self.assertEqual(otp.mask_phone("+919876504821"), "+91 ******4821")
        self.assertEqual(otp.mask_email("parent@gmail.com"), "pa****@gmail.com")


if __name__ == "__main__":
    unittest.main()
