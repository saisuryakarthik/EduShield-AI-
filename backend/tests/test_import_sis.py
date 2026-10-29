"""
Tests for the SIS importer (Phase 1).

These run against a real MySQL database (edushield_test). See
tests/dbtest.py for the safety guard and fixture helpers.
"""

import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"
os.environ["EDUSHIELD_ENV"] = "test"
os.environ["OTP_DELIVERY_MODE"] = "demo"

from dbtest import (  # noqa: E402
    RealDatabaseTestCase,
    add_user,
    connect,
    fresh_fetch_all,
    fresh_fetch_one,
)
from sis_import import (  # noqa: E402
    MENTOR_COLUMNS,
    STUDENT_COLUMNS,
    UNUSABLE_PASSWORD_HASH,
    import_sis,
    read_csv,
)


SAMPLE_DIR = os.path.join(BACKEND_DIR, "scripts", "sample_data")


def mentor(mentor_id="M021", name="Dr One", email="m1@u.edu", dept="CS"):
    return {
        "mentor_id": mentor_id, "name": name,
        "institutional_email": email, "department": dept,
    }


def student(student_id="24STUCHH010221", name="Asha", email="a@u.edu",
            phone="9000000001", dept="CS", section="A", year="1",
            mentor_id="M021", parent_phone="9876500001",
            parent_email="parent@example.com", parent_name="Parent"):
    return {
        "student_id": student_id, "name": name,
        "institutional_email": email, "phone": phone, "department": dept,
        "section": section, "year": year, "mentor_id": mentor_id,
        "parent_name": parent_name, "parent_phone": parent_phone,
        "parent_email": parent_email,
    }


class ImportBase(RealDatabaseTestCase):

    seed_default_fixtures = False

    def run_import(self, students=None, mentors=None, dry_run=False):
        connection = connect(self.db_config)
        try:
            return import_sis(
                connection,
                students=students if students is not None else [student()],
                mentors=mentors if mentors is not None else [mentor()],
                dry_run=dry_run,
                run_by="tester",
            )
        finally:
            connection.close()

    def users(self):
        return {
            r["user_id"]: r
            for r in fresh_fetch_all(
                self.db_config, "SELECT * FROM users"
            )
        }

    def assignments(self):
        return {
            r["student_id"]: r
            for r in fresh_fetch_all(
                self.db_config, "SELECT * FROM mentor_assignments"
            )
        }

    def import_runs(self):
        return fresh_fetch_all(
            self.db_config, "SELECT * FROM sis_import_runs ORDER BY run_id"
        )


class FreshImportTests(ImportBase):

    def test_creates_mentors_students_and_assignments(self):
        summary = self.run_import()

        self.assertEqual(summary["mentors_created"], 1)
        self.assertEqual(summary["students_created"], 1)
        self.assertEqual(summary["assignments_created"], 1)
        self.assertEqual(summary["unassigned"], 0)

        user = self.users()["24STUCHH010221"]
        self.assertEqual(user["role"], "student")
        self.assertEqual(user["account_status"], "pending_activation")
        self.assertEqual(user["password_hash"], UNUSABLE_PASSWORD_HASH)
        self.assertEqual(
            self.assignments()["24STUCHH010221"]["mentor_id"], "M021"
        )

    def test_records_a_run_row(self):
        summary = self.run_import()
        runs = self.import_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], summary["run_id"])
        self.assertEqual(runs[0]["students_created"], 1)


class IdempotencyTests(ImportBase):

    def test_second_import_changes_nothing(self):
        self.run_import()
        summary = self.run_import()

        self.assertEqual(summary["students_created"], 0)
        self.assertEqual(summary["students_updated"], 0)
        self.assertEqual(summary["mentors_created"], 0)
        self.assertEqual(summary["mentors_updated"], 0)
        self.assertEqual(summary["assignments_created"], 0)
        self.assertEqual(summary["assignments_updated"], 0)

    def test_a_changed_field_is_an_update_not_a_duplicate(self):
        self.run_import()
        summary = self.run_import(students=[student(name="Asha R")])

        self.assertEqual(summary["students_created"], 0)
        self.assertEqual(summary["students_updated"], 1)
        self.assertEqual(self.users()["24STUCHH010221"]["name"], "Asha R")
        self.assertEqual(len(self.users()), 2)  # one mentor, one student


class MentorRuleTests(ImportBase):

    def test_blank_mentor_id_keeps_existing_assignment(self):
        self.run_import()
        summary = self.run_import(students=[student(mentor_id="")])

        self.assertEqual(summary["unassigned"], 0)
        self.assertEqual(
            self.assignments()["24STUCHH010221"]["mentor_id"], "M021"
        )

    def test_unknown_mentor_is_skipped_and_counted_unassigned(self):
        self.run_import(students=[student(mentor_id="M999")], mentors=[mentor()])

        summary = self.run_import(
            students=[student(mentor_id="M999")], mentors=[mentor()]
        )
        self.assertNotIn("24STUCHH010221", self.assignments())
        self.assertEqual(summary["unassigned"], 1)
        self.assertTrue(
            any("not found" in w["message"] for w in summary["warnings"])
        )


class WarningTests(ImportBase):

    def test_missing_parent_phone_warns_but_still_imports(self):
        summary = self.run_import(students=[student(parent_phone="")])

        self.assertEqual(summary["students_created"], 1)
        self.assertEqual(len(summary["warnings"]), 1)
        self.assertIn("parent_phone", summary["warnings"][0]["message"])


class DryRunTests(ImportBase):

    def test_dry_run_writes_nothing(self):
        summary = self.run_import(dry_run=True)

        self.assertEqual(summary["students_created"], 1)
        self.assertTrue(summary["dry_run"])
        self.assertEqual(self.users(), {})
        self.assertEqual(self.assignments(), {})
        self.assertEqual(self.import_runs(), [])


class ExistingAccountTests(ImportBase):

    def test_activated_account_keeps_status_and_password(self):
        add_user(
            self.connection,
            user_id="24STUCHH010221", name="Old", email="a@u.edu",
            role="student", account_status="active", password_hash="KEEP",
            department="CS", section="A", year="1",
            phone_number="9000000001", parent_email="parent@example.com",
            parent_phone="9876500001",
        )
        self.run_import(students=[student(name="Asha R")], mentors=[mentor()])

        user = self.users()["24STUCHH010221"]
        self.assertEqual(user["account_status"], "active")
        self.assertEqual(user["password_hash"], "KEEP")
        self.assertEqual(user["name"], "Asha R")


class SampleDataTests(RealDatabaseTestCase):

    seed_default_fixtures = False

    def _read(self):
        students = read_csv(
            os.path.join(SAMPLE_DIR, "students.csv"), STUDENT_COLUMNS
        )
        mentors = read_csv(
            os.path.join(SAMPLE_DIR, "mentors.csv"), MENTOR_COLUMNS
        )
        return students, mentors

    def _import_sample(self):
        """Import the sample files against a DB that already has M021,
        mirroring the live database (M021 exists, so its students assign)."""
        students, mentors = self._read()
        add_user(
            self.connection,
            user_id="M021", name="Harsha", email="harsha@univ.edu",
            role="mentor", password_hash="x",
        )
        connection = connect(self.db_config)
        try:
            summary = import_sis(
                connection, students=students, mentors=mentors,
                run_by="tester",
            )
        finally:
            connection.close()
        return summary

    def test_sample_files_parse(self):
        students, mentors = self._read()

        self.assertEqual(len(students), 15)
        self.assertEqual(len(mentors), 2)

    def test_sample_import_matches_expected_totals(self):
        summary = self._import_sample()

        self.assertEqual(summary["mentors_created"], 2)
        self.assertEqual(summary["students_created"], 15)
        self.assertEqual(summary["assignments_created"], 14)
        self.assertEqual(summary["unassigned"], 1)
        self.assertEqual(len(summary["warnings"]), 1)

        assignments = fresh_fetch_all(
            self.db_config,
            "SELECT student_id, active FROM mentor_assignments "
            "WHERE active = 1",
        )
        assigned_ids = {a["student_id"] for a in assignments}
        self.assertNotIn("24STUCHH011270", assigned_ids)

        self.assertIsNotNone(fresh_fetch_one(
            self.db_config,
            "SELECT user_id FROM users WHERE user_id = '24STUCHH011384'",
        ))


if __name__ == "__main__":
    unittest.main()
