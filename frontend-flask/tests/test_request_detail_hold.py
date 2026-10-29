import importlib.util
import os
import re
import sys
import unittest
from unittest import mock

FRONTEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(FRONTEND_DIR, "app.py")


def load_frontend_app():
    spec = importlib.util.spec_from_file_location("frontend_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.app.template_folder = os.path.join(FRONTEND_DIR, "templates")
    module.app.static_folder = os.path.join(FRONTEND_DIR, "static")
    module.app.testing = True
    return module


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def backend_payload(status, auth_status):
    return {
        "request": {
            "request_id": "REQ_HOLD_TEST",
            "old_phone": "9555000101",
            "new_phone": "9666000101",
            "status": status,
            "auth_status": auth_status,
            "parent_verification_status": auth_status,
            "mentor_id": "M045",
        },
        "security_context": {
            "known_device": 1,
            "location_deviation": 0.0,
            "failed_login_count": 0,
            "recent_password_reset": 0,
            "mfa_verified": 1,
            "phone_change_frequency": 0,
            "login_time_deviation": 0.0,
            "trust_score": 0.9,
        },
        "ai_assessment": {
            "risk_score": 0.1,
            "risk_level": "LOW",
            "risk_factors": [],
        },
        "otp_channels": [
            {"channel": "SMS", "verified": 1, "locked": 0, "attempts": 0},
            {"channel": "EMAIL", "verified": 1, "locked": 0, "attempts": 0},
        ],
    }


class RequestDetailSecurityHoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_app()

    def render_detail(self, status, auth_status):
        payload = backend_payload(status, auth_status)

        with mock.patch.object(
            self.frontend,
            "get_current_user",
            return_value={"user_id": "M045", "role": "mentor", "name": "Mentor"},
        ), mock.patch.object(
            self.frontend.requests,
            "get",
            return_value=FakeResponse(payload),
        ):
            client = self.frontend.app.test_client()
            client.set_cookie("auth_token", "test-token")
            response = client.get("/request-detail/REQ_HOLD_TEST")

        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_security_hold_message_is_accurate_and_approval_is_disabled(self):
        html = self.render_detail("SECURITY_HOLD", "VERIFIED")

        self.assertIn(
            "Security hold in effect. Mentor approval is blocked pending resolution.",
            html,
        )
        self.assertNotIn("The request is ready for your decision.", html)

        approve = re.search(
            r'<button[^>]*data-decision="APPROVED"[^>]*>',
            html,
        )
        self.assertIsNotNone(approve)
        self.assertIn("disabled", approve.group(0))
        self.assertIn(
            'title="Security hold in effect. Mentor approval is blocked pending resolution."',
            approve.group(0),
        )

    def test_verified_pending_request_keeps_approval_available(self):
        html = self.render_detail("PENDING", "VERIFIED")

        self.assertIn("The request is ready for your decision.", html)
        self.assertNotIn("Security hold in effect.", html)

        approve = re.search(
            r'<button[^>]*data-decision="APPROVED"[^>]*>',
            html,
        )
        self.assertIsNotNone(approve)
        self.assertNotIn("disabled", approve.group(0))


if __name__ == "__main__":
    unittest.main()
