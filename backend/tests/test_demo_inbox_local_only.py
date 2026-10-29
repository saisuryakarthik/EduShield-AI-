"""
The demo OTP inbox is an authenticated, local-only debugging aid.

It must never be reachable in production delivery mode or from a remote
address, even if the demo routes are registered.
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
os.environ["OTP_DELIVERY_MODE"] = "demo"
# The repository's backend/.env may target production; this suite is
# explicitly a local-development check so it must opt in.
os.environ["EDUSHIELD_ENV"] = "development"

import app as backend  # noqa: E402


class DemoInboxLocalOnlyTests(unittest.TestCase):
    def request_context(self, remote_address):
        return backend.app.test_request_context(
            "/",
            environ_base={"REMOTE_ADDR": remote_address},
        )

    def test_demo_mode_loopback_is_allowed(self):
        with mock.patch.object(backend, "OTP_DELIVERY_MODE", "demo"), \
                mock.patch.dict(
                    os.environ, {"EDUSHIELD_ENV": "development"}
                ), self.request_context("127.0.0.1"):
            self.assertIsNone(backend._demo_inbox_denial())

    def test_demo_mode_remote_address_is_denied(self):
        with mock.patch.object(backend, "OTP_DELIVERY_MODE", "demo"), \
                mock.patch.dict(
                    os.environ, {"EDUSHIELD_ENV": "development"}
                ), self.request_context("203.0.113.10"):
            response, status = backend._demo_inbox_denial()

        self.assertEqual(status, 403)
        self.assertIn("localhost", response.get_json()["message"])

    def test_production_mode_is_denied_even_on_loopback(self):
        with mock.patch.object(backend, "OTP_DELIVERY_MODE", "production"), \
                mock.patch.dict(
                    os.environ, {"EDUSHIELD_ENV": "development"}
                ), self.request_context("127.0.0.1"):
            response, status = backend._demo_inbox_denial()

        self.assertEqual(status, 403)
        self.assertIn("DEMO mode", response.get_json()["message"])

    def test_production_environment_is_denied_even_in_demo_mode(self):
        with mock.patch.object(backend, "OTP_DELIVERY_MODE", "demo"), \
                mock.patch.dict(
                    os.environ, {"EDUSHIELD_ENV": "production"}
                ), self.request_context("127.0.0.1"):
            response, status = backend._demo_inbox_denial()

        self.assertEqual(status, 403)
        self.assertIn("environment", response.get_json()["message"])

    def test_unknown_environment_is_denied(self):
        with mock.patch.object(backend, "OTP_DELIVERY_MODE", "demo"), \
                mock.patch.dict(
                    os.environ, {"EDUSHIELD_ENV": "staging"}
                ), self.request_context("127.0.0.1"):
            response, status = backend._demo_inbox_denial()

        self.assertEqual(status, 403)
        self.assertIn("environment", response.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
