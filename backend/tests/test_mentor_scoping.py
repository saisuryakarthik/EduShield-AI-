"""
Tests that a mentor only sees and acts on students assigned to them.

Mentor authorisation is driven by mentor_assignments, not users.mentor_id.
A request a mentor does not manage is reported as 404, never 403.

These run against a real MySQL database (edushield_test). See
tests/dbtest.py for the safety guard and fixture helpers.
"""

import os
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
from auth import generate_token  # noqa: E402
from dbtest import (  # noqa: E402
    RealDatabaseTestCase,
    add_assignment,
    add_request,
    add_user,
    connect,
    fresh_fetch_one,
)


MENTOR_1 = "M021"
MENTOR_2 = "M045"
STUDENT_A = "24STUCHH010221"
STUDENT_B = "24STUCHH010238"


class ScopingBase(RealDatabaseTestCase):

    def seed(self):
        add_user(
            self.connection,
            user_id=MENTOR_1, name="One", email="m1@test",
            role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=MENTOR_2, name="Two", email="m2@test",
            role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=STUDENT_A, name="Asha", email="a@test",
            role="student", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=STUDENT_B, name="Bilal", email="b@test",
            role="student", password_hash="x",
        )

        add_assignment(self.connection, STUDENT_A, MENTOR_1)
        add_assignment(self.connection, STUDENT_B, MENTOR_2)

        add_request(
            self.connection,
            request_id="REQ_A", user_id=STUDENT_A, mentor_id=MENTOR_1,
        )
        add_request(
            self.connection,
            request_id="REQ_B", user_id=STUDENT_B, mentor_id=MENTOR_2,
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

    def headers(self, user_id, role):
        return {"Authorization": "Bearer " + generate_token(user_id, role)}

    def list_requests(self, user_id, role):
        resp = self.client.get(
            "/api/phone-change-requests", headers=self.headers(user_id, role)
        )
        return [r["request_id"] for r in resp.get_json()["requests"]]

    def detail(self, request_id, user_id, role):
        return self.client.get(
            f"/api/phone-change-requests/{request_id}",
            headers=self.headers(user_id, role),
        )

    def review(self, request_id, user_id, role, decision="REJECTED"):
        return self.client.patch(
            f"/api/phone-change-requests/{request_id}",
            json={"decision": decision, "reason": "nope"},
            headers=self.headers(user_id, role),
        )


class MentorListScopingTests(ScopingBase):

    def test_mentor_lists_only_assigned_students(self):
        self.assertEqual(self.list_requests(MENTOR_1, "mentor"), ["REQ_A"])
        self.assertEqual(self.list_requests(MENTOR_2, "mentor"), ["REQ_B"])

    def test_student_lists_only_their_own(self):
        self.assertEqual(self.list_requests(STUDENT_A, "student"), ["REQ_A"])


class MentorDetailScopingTests(ScopingBase):

    def test_assigned_mentor_can_read_detail(self):
        self.assertEqual(
            self.detail("REQ_A", MENTOR_1, "mentor").status_code, 200
        )

    def test_unassigned_mentor_gets_404_not_403(self):
        resp = self.detail("REQ_A", MENTOR_2, "mentor")
        self.assertEqual(resp.status_code, 404)


class MentorReviewScopingTests(ScopingBase):

    def test_assigned_mentor_can_review(self):
        resp = self.review("REQ_A", MENTOR_1, "mentor")
        self.assertEqual(resp.status_code, 200)

    def test_unassigned_mentor_gets_404_not_403(self):
        resp = self.review("REQ_A", MENTOR_2, "mentor")
        self.assertEqual(resp.status_code, 404)
        row = fresh_fetch_one(
            self.db_config,
            "SELECT status FROM phone_change_requests WHERE request_id = 'REQ_A'",
        )
        self.assertEqual(row["status"], "PENDING")

    def test_reassignment_moves_access_to_the_new_mentor(self):
        add_assignment(self.connection, STUDENT_A, MENTOR_2, active=1)
        self.assertEqual(
            self.detail("REQ_A", MENTOR_2, "mentor").status_code, 200
        )
        self.assertEqual(
            self.detail("REQ_A", MENTOR_1, "mentor").status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
