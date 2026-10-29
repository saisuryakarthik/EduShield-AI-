"""
Tests for in-app notifications, student soft-delete and mentor nudges.

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
    add_request,
    add_user,
    connect,
    fresh_fetch_all,
    fresh_fetch_one,
)


STUDENT = "24STUCHH010221"
OTHER_STUDENT = "24STUCHH010238"
MENTOR = "M045"
OTHER_MENTOR = "M099"
ADMIN = "ADM_TEST"

NEW_PHONE = "9555666777"


class NotifBase(RealDatabaseTestCase):

    def seed(self):
        add_user(
            self.connection,
            user_id=STUDENT, name="Asha", email="asha@student.test",
            parent_email="parent@example.test", parent_phone="+919876504821",
            phone_number="9000000001", role="student", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=OTHER_STUDENT, name="Bilal", email="bilal@student.test",
            phone_number="9000000002", role="student", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=MENTOR, name="Dr. Harsha", email="harsha@mentor.test",
            phone_number="9000000003", role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=OTHER_MENTOR, name="Dr. Other", email="other@mentor.test",
            phone_number="9000000004", role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=ADMIN, name="Admin", email="admin@test",
            phone_number="9000000005", role="admin", password_hash="x",
        )

        add_assignment(self.connection, STUDENT, MENTOR)

        add_request(
            self.connection,
            request_id="REQ_A", user_id=STUDENT, mentor_id=MENTOR,
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
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.client = backend.app.test_client()

    def _capture_email(self, to_address, subject, body, html=None, **kwargs):
        self.sent_email.append((to_address, subject, body))

    def headers(self, user_id, role):
        return {"Authorization": "Bearer " + generate_token(user_id, role)}

    def student_headers(self):
        return self.headers(STUDENT, "student")

    def mentor_headers(self):
        return self.headers(MENTOR, "mentor")

    def admin_headers(self):
        return self.headers(ADMIN, "admin")

    # --- backend calls -------------------------------------------
    def notify(self, request_id="REQ_A", headers=None):
        return self.client.post(
            f"/api/phone-change-requests/{request_id}/notify-mentor",
            headers=headers if headers is not None else self.student_headers(),
        )

    def soft_delete(self, request_id="REQ_A", headers=None):
        return self.client.post(
            f"/api/phone-change-requests/{request_id}/delete",
            headers=headers if headers is not None else self.student_headers(),
        )

    def list_ids(self, headers):
        resp = self.client.get(
            "/api/phone-change-requests", headers=headers
        )
        return [r["request_id"] for r in resp.get_json()["requests"]]

    def list_notifications(self, headers):
        resp = self.client.get("/api/notifications", headers=headers)
        return resp

    def mark_read(self, notification_id, headers):
        return self.client.post(
            f"/api/notifications/{notification_id}/read", headers=headers
        )

    # --- DB readers ----------------------------------------------
    def notification_rows(self, user_id=None):
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

    def request_row(self, request_id="REQ_A"):
        return fresh_fetch_one(
            self.db_config,
            "SELECT * FROM phone_change_requests WHERE request_id = %s",
            (request_id,),
        )

    def audit_actions(self):
        return [
            r["action"]
            for r in fresh_fetch_all(
                self.db_config, "SELECT action FROM audit_logs"
            )
        ]

    def set_request_status(self, request_id, status):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "UPDATE phone_change_requests SET status = %s "
                "WHERE request_id = %s",
                (status, request_id),
            )
            self.connection.commit()
        finally:
            cursor.close()


# ------------------------------------------------------------------
# Notify mentor
# ------------------------------------------------------------------

class NotifyMentorTests(NotifBase):

    def test_notify_creates_notification_email_and_audit(self):
        resp = self.notify()
        self.assertEqual(resp.status_code, 200)

        rows = self.notification_rows(MENTOR)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "MENTOR_NOTIFIED")
        self.assertEqual(rows[0]["request_id"], "REQ_A")
        self.assertIsNone(rows[0]["read_at"])

        self.assertIn("MENTOR_NOTIFIED", self.audit_actions())

        mentor_mails = [t for t, _, _ in self.sent_email if t == "harsha@mentor.test"]
        self.assertEqual(len(mentor_mails), 1)

    def test_notify_requires_an_active_assignment(self):
        add_assignment(self.connection, STUDENT, MENTOR, active=0)
        resp = self.notify()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.notification_rows(MENTOR), [])

    def test_notify_only_works_on_pending_requests(self):
        self.set_request_status("REQ_A", "APPROVED")
        resp = self.notify()
        self.assertEqual(resp.status_code, 409)

    def test_notify_of_someone_elses_request_is_404(self):
        resp = self.notify(headers=self.headers(OTHER_STUDENT, "student"))
        self.assertEqual(resp.status_code, 404)

    def test_notify_is_limited_to_one_per_six_hours(self):
        self.assertEqual(self.notify().status_code, 200)

        second = self.notify()
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)

        # The cooldown did not create a second notification.
        self.assertEqual(len(self.notification_rows(MENTOR)), 1)

    def test_notify_is_capped_at_three_per_request(self):
        # Three notifications, each aged past the six-hour cooldown so the
        # per-request ceiling (not the cooldown) is what stops the fourth.
        for _ in range(3):
            self.assertEqual(self.notify().status_code, 200)
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    "UPDATE notifications SET created_at = "
                    "TIMESTAMPADD(HOUR, -7, created_at) "
                    "WHERE type = 'MENTOR_NOTIFIED'"
                )
                self.connection.commit()
            finally:
                cursor.close()

        fourth = self.notify()
        self.assertEqual(fourth.status_code, 429)
        self.assertEqual(len(self.notification_rows(MENTOR)), 3)

    def test_notify_message_has_no_secrets(self):
        self.notify()
        message = self.notification_rows(MENTOR)[0]["message"]

        # No 6-digit OTP-like codes, no long hex hashes, no phone numbers.
        self.assertIsNone(re.search(r"\b\d{6}\b", message))
        self.assertIsNone(re.search(r"\b[0-9a-f]{32,}\b", message))
        self.assertIsNone(re.search(r"\b\d{10}\b", message))


# ------------------------------------------------------------------
# Notifications inbox
# ------------------------------------------------------------------

class NotificationInboxTests(NotifBase):

    def test_inbox_returns_only_own_notifications(self):
        self.notify()

        # Give the other mentor an unrelated notification directly.
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO notifications (user_id, type, request_id, message) "
                "VALUES (%s, 'PARENT_VERIFIED', 'REQ_A', 'other')",
                (OTHER_MENTOR,),
            )
            self.connection.commit()
        finally:
            cursor.close()

        mine = self.list_notifications(self.mentor_headers()).get_json()
        self.assertEqual(mine["count"], 1)
        self.assertEqual(mine["unread"], 1)
        self.assertTrue(all(
            n["type"] == "MENTOR_NOTIFIED" for n in mine["notifications"]
        ))

    def test_mark_read_only_affects_own_notification(self):
        self.notify()
        nid = self.notification_rows(MENTOR)[0]["notification_id"]

        # A different user cannot read it.
        foreign = self.mark_read(nid, self.headers(OTHER_MENTOR, "mentor"))
        self.assertEqual(foreign.status_code, 404)

        # Still unread for the owner.
        self.assertIsNone(self.notification_rows(MENTOR)[0]["read_at"])

        own = self.mark_read(nid, self.mentor_headers())
        self.assertEqual(own.status_code, 200)
        self.assertIsNotNone(self.notification_rows(MENTOR)[0]["read_at"])

    def test_mark_read_unknown_id_is_404(self):
        resp = self.mark_read(999999, self.mentor_headers())
        self.assertEqual(resp.status_code, 404)

    def test_unread_count_drops_after_reading(self):
        self.notify()
        nid = self.notification_rows(MENTOR)[0]["notification_id"]

        self.mark_read(nid, self.mentor_headers())

        after = self.list_notifications(self.mentor_headers()).get_json()
        self.assertEqual(after["unread"], 0)
        self.assertTrue(after["notifications"][0]["read"])


# ------------------------------------------------------------------
# Soft delete
# ------------------------------------------------------------------

class SoftDeleteTests(NotifBase):

    def test_pending_request_can_be_hidden(self):
        resp = self.soft_delete()
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(self.request_row()["deleted_by_student"], 1)
        self.assertIn("REQUEST_DELETED_BY_STUDENT", self.audit_actions())

    def test_hidden_request_leaves_student_list_but_stays_for_mentor(self):
        self.soft_delete()

        self.assertNotIn("REQ_A", self.list_ids(self.student_headers()))
        self.assertIn("REQ_A", self.list_ids(self.mentor_headers()))

    def test_hidden_request_stays_visible_to_admin(self):
        self.soft_delete()

        self.assertIn("REQ_A", self.list_ids(self.admin_headers()))

    def test_admin_sees_requests_outside_own_assignments(self):
        self.assertIn("REQ_A", self.list_ids(self.admin_headers()))

    def test_cancelled_request_can_be_hidden(self):
        self.set_request_status("REQ_A", "CANCELLED")
        self.assertEqual(self.soft_delete().status_code, 200)

    def test_approved_request_cannot_be_hidden(self):
        self.set_request_status("REQ_A", "APPROVED")
        resp = self.soft_delete()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.request_row()["deleted_by_student"], 0)

    def test_soft_delete_of_someone_elses_request_is_404(self):
        resp = self.soft_delete(headers=self.headers(OTHER_STUDENT, "student"))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.request_row()["deleted_by_student"], 0)

    def test_row_is_never_removed(self):
        self.soft_delete()
        self.assertIsNotNone(self.request_row())


# ------------------------------------------------------------------
# Event hooks
# ------------------------------------------------------------------

class HookBase(NotifBase):
    """Drives the real parent-verification flow to exercise the hooks."""

    def seed(self):
        # Users and assignment only: the submit() call creates the one
        # open request this flow needs (a pre-seeded PENDING request
        # would make the live submission return 409).
        add_user(
            self.connection,
            user_id=STUDENT, name="Asha", email="asha@student.test",
            parent_email="parent@example.test", parent_phone="+919876504821",
            phone_number="9000000001", role="student", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=MENTOR, name="Dr. Harsha", email="harsha@mentor.test",
            phone_number="9000000003", role="mentor", password_hash="x",
        )
        add_assignment(self.connection, STUDENT, MENTOR)

    def after_setup(self):
        super().after_setup()
        # Boostrap a brand-new request through the live submission API so
        # the parent OTP rows and link token exist.
        self.sent_sms = []
        sms_patch = mock.patch.object(
            backend, "send_sms", side_effect=self._capture_sms
        )
        sms_patch.start()
        self.addCleanup(sms_patch.stop)

    def _capture_sms(self, to_address, text, **kwargs):
        self.sent_sms.append((to_address, text))

    def submit(self):
        return self.client.post(
            "/api/phone-change-requests",
            json={"new_phone": NEW_PHONE},
            headers=self.student_headers(),
        )

    def _parent_email_body(self):
        bodies = [
            b for t, _, b in self.sent_email if t == "parent@example.test"
        ]
        return bodies[-1]

    def sms_code(self):
        text = self.sent_sms[-1][1]
        return re.search(r"code is (\d{6})", text).group(1)

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

    def report(self, token):
        return self.client.post(f"/parent/report/{token}")


class ParentVerifiedHookTests(HookBase):

    def test_parent_verification_creates_mentor_notification(self):
        self.submit()
        token = self.parent_token()
        self.verify(token, "sms", self.sms_code())
        self.verify(token, "email", self.email_code())

        rows = [r for r in self.notification_rows(MENTOR)
                if r["type"] == "PARENT_VERIFIED"]
        self.assertEqual(len(rows), 1)


class SecurityHoldHookTests(HookBase):

    def test_parent_report_creates_mentor_notification(self):
        self.submit()
        token = self.parent_token()
        resp = self.report(token)
        self.assertEqual(resp.status_code, 200)

        rows = [r for r in self.notification_rows(MENTOR)
                if r["type"] == "SECURITY_HOLD"]
        self.assertEqual(len(rows), 1)


class CancelAfterNotifyHookTests(HookBase):

    def test_cancelling_after_notify_tells_the_mentor(self):
        self.submit()
        request_id = self.list_ids(self.student_headers())[0]

        self.assertEqual(
            self.client.post(
                f"/api/phone-change-requests/{request_id}/notify-mentor",
                headers=self.student_headers(),
            ).status_code,
            200,
        )

        self.assertEqual(
            self.client.post(
                f"/api/phone-change-requests/{request_id}/cancel",
                headers=self.student_headers(),
            ).status_code,
            200,
        )

        types = [r["type"] for r in self.notification_rows(MENTOR)]
        self.assertIn("MENTOR_NOTIFIED", types)
        self.assertIn("REQUEST_CANCELLED", types)

    def test_cancelling_without_notify_does_not_ping_the_mentor(self):
        self.submit()
        request_id = self.list_ids(self.student_headers())[0]

        self.client.post(
            f"/api/phone-change-requests/{request_id}/cancel",
            headers=self.student_headers(),
        )

        types = [r["type"] for r in self.notification_rows(MENTOR)]
        self.assertNotIn("REQUEST_CANCELLED", types)


if __name__ == "__main__":
    unittest.main()
