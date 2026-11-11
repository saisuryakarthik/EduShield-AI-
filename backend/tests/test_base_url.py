import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["EDUSHIELD_OTP_PEPPER"] = "test-pepper-value"
os.environ["EDUSHIELD_SMS_PROVIDER"] = "disabled"
os.environ["EDUSHIELD_ENV"] = "test"
os.environ["OTP_DELIVERY_MODE"] = "demo"

import app as backend


class BaseUrlTests(unittest.TestCase):
    def test_base_url_uses_configured_value(self):
        os.environ["EDUSHIELD_BASE_URL"] = "https://example.workers.dev"
        self.assertEqual(backend._base_url(), "https://example.workers.dev")

    def test_base_url_strips_trailing_slash(self):
        os.environ["EDUSHIELD_BASE_URL"] = "https://example.workers.dev/"
        self.assertEqual(backend._base_url(), "https://example.workers.dev")


if __name__ == "__main__":
    unittest.main()
