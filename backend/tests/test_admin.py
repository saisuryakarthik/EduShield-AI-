"""
Tests for the admin portal (Phase 1).

These run against a real MySQL database (edushield_test). See
tests/dbtest.py for the safety guard and fixture helpers.

Run from backend/:
    python -m unittest discover -s tests -v
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
    add_user,
    connect,
    fresh_fetch_one,
)


ADMIN = "ADM1"
MENTOR_1 = "M021"
MENTOR_2 = "M045"
STUDENT_A = "24STUCHH010221"
STUDENT_B = "24STUCHH010238"


class AdminBase(RealDatabaseTestCase):

    def seed(self):
        add_user(
            self.connection,
            user_id=ADMIN, name="Admin", email="admin@univ.test",
            role="admin", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=MENTOR_1, name="Mentor One", email="m1@univ.test",
            role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=MENTOR_2, name="Mentor Two", email="m2@univ.test",
            role="mentor", password_hash="x",
        )
        add_user(
            self.connection,
            user_id=STUDENT_A, name="Asha", email="a@univ.test",
            role="student", password_hash="x", account_status="active",
        )
        add_user(
            self.connection,
            user_id=STUDENT_B, name="Bilal", email="b@univ.test",
            role="student", password_hash="x",
            account_status="pending_activation",
        )
        add_assignment(self.connection, STUDENT_A, MENTOR_1)

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

    def admin(self):
        return self.headers(ADMIN, "admin")

    def assignment(self, student_id):
        return fresh_fetch_one(
            self.db_config,
            "SELECT mentor_id, active FROM mentor_assignments "
            "WHERE student_id = %s",
            (student_id,),
        )


class AdminAuthorisationTests(AdminBase):

    def test_student_is_forbidden(self):
        resp = self.client.get(
            "/api/admin/summary",
            headers=self.headers(STUDENT_A, "student"),
        )
        self.assertEqual(resp.status_code, 403)

    def test_mentor_is_forbidden(self):
        resp = self.client.get(
            "/api/admin/summary",
            headers=self.headers(MENTOR_1, "mentor"),
        )
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_unauthorised(self):
        resp = self.client.get("/api/admin/summary")
        self.assertEqual(resp.status_code, 401)


class AdminSummaryTests(AdminBase):

    def test_summary_counts_match_seeding(self):
        resp = self.client.get("/api/admin/summary", headers=self.admin())
        self.assertEqual(resp.status_code, 200)

        summary = resp.get_json()["summary"]
        self.assertEqual(summary["students_total"], 2)
        self.assertEqual(summary["students_active"], 1)
        self.assertEqual(summary["students_pending"], 1)
        self.assertEqual(summary["mentors_total"], 2)
        self.assertEqual(summary["unassigned_students"], 1)
        self.assertEqual(summary["open_requests"], 0)


class AdminAssignmentTests(AdminBase):

    def bulk(self, assignments, dry_run=None):
        payload = {"assignments": assignments}
        if dry_run is not None:
            payload["dry_run"] = dry_run
        return self.client.post(
            "/api/admin/assignments/bulk",
            json=payload,
            headers=self.admin(),
        )

    def test_bulk_assign_creates_then_updates(self):
        resp = self.bulk([{"student_id": STUDENT_B, "mentor_id": MENTOR_1}])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["created"], 1)
        self.assertEqual(self.assignment(STUDENT_B)["mentor_id"], MENTOR_1)

        resp = self.bulk([{"student_id": STUDENT_B, "mentor_id": MENTOR_2}])
        self.assertEqual(resp.get_json()["updated"], 1)
        self.assertEqual(self.assignment(STUDENT_B)["mentor_id"], MENTOR_2)

    def test_bulk_reports_unknown_mentor(self):
        resp = self.bulk([{"student_id": STUDENT_B, "mentor_id": "M999"}])
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["created"], 0)
        self.assertEqual(len(body["failed"]), 1)

    def test_bulk_dry_run_reports_without_writing(self):
        resp = self.bulk(
            [{"student_id": STUDENT_B, "mentor_id": MENTOR_1}],
            dry_run=True,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["updated"], 0)
        # Nothing was persisted.
        self.assertIsNone(self.assignment(STUDENT_B))

    def test_bulk_dry_run_does_not_change_an_existing_assignment(self):
        resp = self.bulk(
            [{"student_id": STUDENT_A, "mentor_id": MENTOR_2}],
            dry_run=True,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["updated"], 1)
        # STUDENT_A is still with MENTOR_1.
        self.assertEqual(self.assignment(STUDENT_A)["mentor_id"], MENTOR_1)

    def test_unassign_deactivates_the_assignment(self):
        resp = self.client.post(
            "/api/admin/assignments/unassign",
            json={"student_ids": [STUDENT_A]},
            headers=self.admin(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["unassigned"], 1)
        self.assertEqual(self.assignment(STUDENT_A)["active"], 0)

    def test_bulk_rejects_empty_payload(self):
        resp = self.client.post(
            "/api/admin/assignments/bulk",
            json={"assignments": []},
            headers=self.admin(),
        )
        self.assertEqual(resp.status_code, 400)


class AdminUserListTests(AdminBase):

    def test_list_filters_by_role(self):
        resp = self.client.get(
            "/api/admin/users?role=student", headers=self.admin()
        )
        self.assertEqual(resp.status_code, 200)
        users = resp.get_json()["users"]
        self.assertEqual(len(users), 2)
        self.assertTrue(all(u["role"] == "student" for u in users))

    def test_list_shows_mentor_for_assigned_student(self):
        resp = self.client.get(
            "/api/admin/users?role=student", headers=self.admin()
        )
        users = {u["user_id"]: u for u in resp.get_json()["users"]}
        self.assertEqual(users[STUDENT_A]["mentor_id"], MENTOR_1)
        self.assertIsNone(users[STUDENT_B]["mentor_id"])


if __name__ == "__main__":
    unittest.main()
