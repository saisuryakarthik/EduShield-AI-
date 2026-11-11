import importlib.util
import os
import sys
import unittest
from unittest import mock

FRONTEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = os.path.join(FRONTEND_DIR, "app.py")

sys.path.insert(0, FRONTEND_DIR)


def load_frontend_app():
    spec = importlib.util.spec_from_file_location("frontend_app_admin_dashboard_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.app.template_folder = os.path.join(FRONTEND_DIR, "templates")
    module.app.static_folder = os.path.join(FRONTEND_DIR, "static")
    module.app.testing = True
    return module


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class AdminDashboardRequestsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = load_frontend_app()

    def _client_for(self, requests_payload):
        def fake_get(url, *args, **kwargs):
            if "admin/summary" in url:
                return FakeResponse({"success": True, "summary": {"students_total": 1}})
            if "phone-change-requests" in url:
                return FakeResponse({"success": True, "requests": requests_payload})
            return FakeResponse({}, 404)

        with mock.patch.object(
            self.frontend, "get_current_user",
            return_value={"user_id": "ADM1", "role": "admin", "name": "Admin"},
        ), mock.patch.object(
            self.frontend.requests, "get", side_effect=fake_get
        ):
            client = self.frontend.app.test_client()
            client.set_cookie("auth_token", "test-token")
            response = client.get("/admin-dashboard")
            return response

    def test_admin_dashboard_receives_requests(self):
        response = self._client_for([
            {"request_id": "REQ_ADMIN_TEST", "user_id": "S1",
             "status": "PENDING", "risk_level": "HIGH", "risk_score": 90,
             "risk_factors": [], "old_phone": "1", "new_phone": "2",
             "requested_at": "2026-01-01", "auth_status": "VERIFIED"}
        ])
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"REQ_ADMIN_TEST", response.get_data())

    def test_admin_dashboard_empty_requests(self):
        response = self._client_for([])
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No phone change requests recorded.", response.get_data())

    def test_admin_dashboard_backend_failure(self):
        with mock.patch.object(
            self.frontend, "get_current_user",
            return_value={"user_id": "ADM1", "role": "admin", "name": "Admin"},
        ), mock.patch.object(
            self.frontend.requests, "get",
            side_effect=self.frontend.requests.RequestException("boom"),
        ):
            client = self.frontend.app.test_client()
            client.set_cookie("auth_token", "test-token")
            response = client.get("/admin-dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"boom", response.get_data())

    def test_admin_dashboard_unauthorized(self):
        client = self.frontend.app.test_client()
        response = client.get("/admin-dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/login")

    def test_admin_dashboard_wrong_role(self):
        with mock.patch.object(
            self.frontend, "get_current_user",
            return_value={"user_id": "S1", "role": "student", "name": "Student"},
        ):
            client = self.frontend.app.test_client()
            client.set_cookie("auth_token", "test-token")
            response = client.get("/admin-dashboard")
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()