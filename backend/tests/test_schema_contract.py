"""
Regression tests for the schema the backend expects.

The live database was missing migration 004 (deleted_by_student and
notifications) and all of migration 005, even though 006 was present.
These tests lock the complete contract in place so a partial upgrade
fails loudly in CI instead of at a user-facing endpoint.

Run from backend/:
    python -m unittest tests.test_schema_contract -v
"""

import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dbtest import RealDatabaseTestCase  # noqa: E402


EXPECTED_TABLES = {
    "users",
    "phone_change_requests",
    "phone_change_otps",
    "ai_assessments",
    "ai_assessment_status",
    "revoked_tokens",
    "audit_logs",
    "mentor_reviews",
    "security_context",
    "security_events",
    "mentor_assignments",
    "account_activation_otps",
    "sis_import_runs",
    "notifications",
    "notification_deliveries",
    "request_timeline",
    "request_sla_policies",
    "security_alerts",
    "model_registry",
    "model_evaluations",
    "model_predictions",
    "account_recoveries",
    "sis_import_reports",
    "schema_migrations",
}

EXPECTED_PHONE_COLUMNS = {
    "request_id",
    "user_id",
    "old_phone",
    "new_phone",
    "requested_at",
    "auth_status",
    "parent_verification_status",
    "parent_verified_at",
    "parent_token_hash",
    "parent_token_expires_at",
    "status",
    "mentor_id",
    "reviewed_at",
    "rejection_reason",
    "deleted_by_student",
}


class SchemaContractTests(RealDatabaseTestCase):

    seed_default_fixtures = False

    def table_names(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute("SHOW TABLES")
            return {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()

    def column_names(self, table):
        cursor = self.connection.cursor()
        try:
            cursor.execute(f"SHOW COLUMNS FROM {table}")
            return {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()

    def test_all_required_tables_exist(self):
        missing = EXPECTED_TABLES - self.table_names()
        self.assertEqual(missing, set())

    def test_phone_change_requests_has_all_expected_columns(self):
        missing = EXPECTED_PHONE_COLUMNS - self.column_names(
            "phone_change_requests"
        )
        self.assertEqual(missing, set())

    def test_deleted_by_student_is_not_nullable_and_defaults_to_zero(self):
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SHOW COLUMNS FROM phone_change_requests "
                "LIKE 'deleted_by_student'"
            )
            column = cursor.fetchone()
        finally:
            cursor.close()

        self.assertIsNotNone(column)
        self.assertEqual(column["Null"], "NO")
        self.assertEqual(str(column["Default"]), "0")

    def test_ai_assessment_is_unique_per_request(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'ai_assessments' "
                "AND INDEX_NAME = 'uq_ai_assessment_request' "
                "AND NON_UNIQUE = 0"
            )
            self.assertIsNotNone(cursor.fetchone())
        finally:
            cursor.close()

    def test_migration_ledger_records_expected_state(self):
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT version, status FROM schema_migrations "
                "WHERE version IN ('001','002','003','004','005','006','007')"
            )
            rows = {row["version"]: row["status"] for row in cursor.fetchall()}
        finally:
            cursor.close()

        self.assertEqual(rows["003"], "deferred")
        for version in ("001", "002", "004", "005", "006", "007"):
            self.assertEqual(rows[version], "applied")


if __name__ == "__main__":
    unittest.main()
