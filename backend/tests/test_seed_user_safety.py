"""The local password reset utility must not run unattended or in production."""

import os
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import seed_user  # noqa: E402


class SeedUserSafetyTests(unittest.TestCase):
    def test_refuses_without_apply_before_prompting(self):
        with mock.patch("builtins.input") as prompt:
            result = seed_user.main(["S1024"])

        self.assertEqual(result, 1)
        prompt.assert_not_called()

    def test_production_environment_is_refused(self):
        env = {
            "EDUSHIELD_ENV": "production",
            "EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET": "1",
        }
        with mock.patch.dict(os.environ, env):
            error = seed_user._validate_environment()

        self.assertIsNotNone(error)
        self.assertIn("EDUSHIELD_ENV", error)

    def test_missing_reset_acknowledgement_is_refused(self):
        env = {
            "EDUSHIELD_ENV": "test",
            "EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET": "",
        }
        with mock.patch.dict(os.environ, env):
            error = seed_user._validate_environment()

        self.assertIsNotNone(error)
        self.assertIn("EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET", error)

    def test_development_with_explicit_reset_is_allowed(self):
        env = {
            "EDUSHIELD_ENV": "development",
            "EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET": "1",
        }
        with mock.patch.dict(os.environ, env):
            self.assertIsNone(seed_user._validate_environment())


if __name__ == "__main__":
    unittest.main()
