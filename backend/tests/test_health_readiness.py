"""Readiness must reflect database reachability without leaking details."""

import os
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"
os.environ["EDUSHIELD_ENV"] = "test"
os.environ["OTP_DELIVERY_MODE"] = "demo"

import app as backend  # noqa: E402


class FakeCursor:
    def execute(self, statement):
        self.statement = statement

    def fetchone(self):
        return (1,)

    def close(self):
        pass


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    def close(self):
        pass


class HealthReadinessTests(unittest.TestCase):
    def client(self):
        backend.app.testing = True
        return backend.app.test_client()

    def test_ready_when_database_answers(self):
        with mock.patch.object(
            backend, "get_db", return_value=FakeConnection()
        ):
            response = self.client().get("/api/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ready")

    def test_not_ready_when_database_fails_without_leaking_error(self):
        with mock.patch.object(
            backend,
            "get_db",
            side_effect=RuntimeError("password=super-secret dsn"),
        ):
            response = self.client().get("/api/health/ready")

        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "not_ready")
        self.assertNotIn("super-secret", body)
        self.assertNotIn("RuntimeError", body)

    def test_liveness_does_not_touch_the_database(self):
        with mock.patch.object(backend, "get_db") as get_db:
            response = self.client().get("/api/health")

        self.assertEqual(response.status_code, 200)
        get_db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
