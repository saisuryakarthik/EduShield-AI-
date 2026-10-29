"""
Tests for OTP delivery in DEMO and PRODUCTION modes.

No test performs a real network call or sends a real message. The provider
HTTP responses are mocked with the exact response shapes documented by
2Factor and Brevo.
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
os.environ["OTP_DELIVERY_MODE"] = "demo"

import notifications
import otp_delivery
from notifications import DeliveryError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class DemoModeDeliveryTests(unittest.TestCase):
    def setUp(self):
        otp_delivery.clear_demo_sms_inbox()
        otp_delivery.clear_demo_email_inbox()
        patcher = mock.patch.object(
            otp_delivery, "OTP_DELIVERY_MODE", "demo"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_demo_sms_provider_receives_existing_otp(self):
        provider = otp_delivery.DemoSMSProvider()
        result = provider.send_sms("+919876543210", "123456", request_id="REQ123")
        self.assertTrue(result.get("success"))
        inbox = otp_delivery.get_demo_sms_inbox()
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["code"], "123456")
        self.assertEqual(inbox[0]["mode"], "DEMO_ONLY")

    def test_demo_mode_does_not_call_2factor(self):
        with mock.patch.object(otp_delivery.twofactor_provider, "send_sms") as m:
            provider = otp_delivery.get_sms_provider()
            self.assertIsInstance(provider, otp_delivery.DemoSMSProvider)
            provider.send_sms("+911234567890", "654321")
            m.assert_not_called()

    def test_only_demo_mechanism_can_reveal_sms_otp(self):
        otp_delivery.clear_demo_sms_inbox()
        otp_delivery.demo_sms_provider.send_sms("+911111111111", "999888", request_id="REQX")
        inbox = otp_delivery.get_demo_sms_inbox()
        self.assertTrue(all(e["mode"] == "DEMO_ONLY" for e in inbox))
        self.assertIn("code", inbox[0])

    def test_demo_email_provider_does_not_call_brevo(self):
        with mock.patch.object(otp_delivery.brevo_email_provider, "send_email") as m:
            provider = otp_delivery.get_email_provider()
            self.assertIsInstance(provider, otp_delivery.DemoEmailProvider)
            result = provider.send_email(
                "parent@example.test",
                "Verify",
                "Your code is 123456",
            )
            m.assert_not_called()

        self.assertTrue(result.get("demo_only"))
        inbox = otp_delivery.get_demo_email_inbox()
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["mode"], "DEMO_ONLY")
        self.assertIn("123456", inbox[0]["body"])


class ProductionModeSelectionTests(unittest.TestCase):
    def test_production_mode_selects_2factor(self):
        with mock.patch.object(otp_delivery, "OTP_DELIVERY_MODE", "production"):
            self.assertIsInstance(
                otp_delivery.get_sms_provider(),
                otp_delivery.TwoFactorProvider,
            )

    def test_brevo_provider_selected_for_email_in_production(self):
        with mock.patch.object(otp_delivery, "OTP_DELIVERY_MODE", "production"):
            provider = otp_delivery.get_email_provider()
            self.assertIsInstance(provider, otp_delivery.BrevoEmailProvider)

    def test_notifications_can_import_delivery_layer(self):
        mode, email_fn, sms_fn = notifications._otp_delivery()
        self.assertIn(mode, ("demo", "production"))
        self.assertTrue(callable(email_fn))
        self.assertTrue(callable(sms_fn))


class TwoFactorProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = otp_delivery.TwoFactorProvider()

    def test_success_response_is_verified_not_just_http_200(self):
        response = FakeResponse(
            200, {"Status": "Success", "Details": "session-123"}
        )
        with mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", "test-2factor-key"
        ), mock.patch.object(
            otp_delivery.requests, "post", return_value=response
        ) as post:
            result = self.provider.send_sms("+919876543210", "123456")

        self.assertTrue(result["success"])
        self.assertEqual(result["session_id"], "session-123")
        url = post.call_args.args[0]
        self.assertIn("/SMS/919876543210/123456", url)
        self.assertNotIn("+919876543210", url)

    def test_custom_otp_template_is_appended_and_encoded(self):
        response = FakeResponse(
            200, {"Status": "Success", "Details": "session-123"}
        )
        with mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", "test-2factor-key"
        ), mock.patch.object(
            otp_delivery, "TWOFACTOR_TEMPLATE_NAME", "OTP Template"
        ), mock.patch.object(
            otp_delivery.requests, "post", return_value=response
        ) as post:
            self.provider.send_sms("+919876543210", "123456")

        url = post.call_args.args[0]
        self.assertTrue(url.endswith("/SMS/919876543210/123456/OTP%20Template"))

    def test_http_200_with_error_status_is_a_failure(self):
        response = FakeResponse(
            200, {"Status": "Error", "Details": "Invalid API Key"}
        )
        with mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", "test-2factor-key"
        ), mock.patch.object(
            otp_delivery.requests, "post", return_value=response
        ):
            with self.assertRaisesRegex(
                DeliveryError, r"status=Error.*Invalid API Key"
            ):
                self.provider.send_sms("+919876543210", "123456")

    def test_error_details_redact_key_otp_and_phone(self):
        key = "test-2factor-key"
        response = FakeResponse(
            401,
            {
                "Status": "Error",
                "Details": f"key {key} code 123456 phone 919876543210 rejected",
            },
        )
        with mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", key
        ), mock.patch.object(
            otp_delivery.requests, "post", return_value=response
        ):
            with self.assertRaises(DeliveryError) as caught:
                self.provider.send_sms("+919876543210", "123456")

        message = str(caught.exception)
        self.assertNotIn(key, message)
        self.assertNotIn("123456", message)
        self.assertNotIn("919876543210", message)

    def test_missing_key_fails_before_network_access(self):
        with mock.patch.object(otp_delivery, "TWOFACTOR_API_KEY", ""), \
                mock.patch.object(otp_delivery.requests, "post") as post:
            with self.assertRaisesRegex(DeliveryError, "not configured"):
                self.provider.send_sms("+919876543210", "123456")
            post.assert_not_called()

    def test_malformed_otp_is_rejected_before_network_access(self):
        with mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", "test-2factor-key"
        ), mock.patch.object(otp_delivery.requests, "post") as post:
            with self.assertRaisesRegex(DeliveryError, "6-digit OTP"):
                self.provider.send_sms("+919876543210", "12ab")
            post.assert_not_called()


class BrevoProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = otp_delivery.BrevoEmailProvider()
        patches = [
            mock.patch.object(otp_delivery, "BREVO_API_KEY", "test-brevo-key"),
            mock.patch.object(
                otp_delivery, "BREVO_SENDER_EMAIL", "sender@example.test"
            ),
            mock.patch.dict(
                os.environ,
                {
                    "BREVO_API_KEY": "test-brevo-key",
                    "BREVO_SENDER_EMAIL": "sender@example.test",
                },
            ),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self):
        return self.provider.send_email(
            "parent@example.test", "subject", "body"
        )

    def test_success_response_returns_message_id(self):
        response = FakeResponse(201, {"messageId": "<msg@brevo>"})
        with mock.patch.object(
            otp_delivery.requests, "post", return_value=response
        ):
            result = self.send()

        self.assertTrue(result["success"])
        self.assertEqual(result["message_id"], "<msg@brevo>")

    def test_http_error_is_a_failure_with_safe_detail(self):
        response = FakeResponse(
            400,
            {"code": "invalid_parameter", "message": "sender email is invalid"},
        )
        with mock.patch.object(
            otp_delivery.requests, "post", return_value=response
        ):
            with self.assertRaisesRegex(
                DeliveryError, r"HTTP 400.*sender email is invalid"
            ):
                self.send()

    def test_missing_key_fails_before_network_access(self):
        with mock.patch.object(otp_delivery, "BREVO_API_KEY", ""), \
                mock.patch.object(otp_delivery.requests, "post") as post:
            with self.assertRaisesRegex(DeliveryError, "not configured"):
                self.send()
            post.assert_not_called()


class ProductionConfigValidationTests(unittest.TestCase):

    def test_demo_mode_needs_no_provider_credentials(self):
        with mock.patch.object(
            otp_delivery, "OTP_DELIVERY_MODE", "demo"
        ), mock.patch.dict(
            os.environ, {"EDUSHIELD_ENV": "development"}
        ), mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", ""
        ), mock.patch.object(
            otp_delivery, "BREVO_API_KEY", ""
        ):
            self.assertTrue(otp_delivery.validate_delivery_config())

    def test_production_missing_credentials_fails_safely(self):
        with mock.patch.object(
            otp_delivery, "OTP_DELIVERY_MODE", "production"
        ), mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", ""
        ), mock.patch.object(
            otp_delivery, "BREVO_API_KEY", ""
        ), mock.patch.dict(
            os.environ,
            {"EDUSHIELD_ENV": "production", "EDUSHIELD_EMAIL": ""},
        ), mock.patch.object(
            otp_delivery, "BREVO_SENDER_EMAIL", ""
        ):
            with self.assertRaises(DeliveryError) as caught:
                otp_delivery.validate_delivery_config()

        message = str(caught.exception)
        self.assertIn("TWOFACTOR_API_KEY", message)
        self.assertIn("BREVO_API_KEY", message)
        self.assertIn("BREVO_SENDER_EMAIL", message)

    def test_production_selects_real_providers(self):
        with mock.patch.object(
            otp_delivery, "OTP_DELIVERY_MODE", "production"
        ), mock.patch.object(
            otp_delivery, "TWOFACTOR_API_KEY", "test-2factor-key"
        ), mock.patch.object(
            otp_delivery, "BREVO_API_KEY", "test-brevo-key"
        ), mock.patch.object(
            otp_delivery, "BREVO_SENDER_EMAIL", "sender@example.test"
        ), mock.patch.dict(os.environ, {"EDUSHIELD_ENV": "production"}):
            self.assertTrue(otp_delivery.validate_delivery_config())

    def test_demo_mode_is_rejected_in_production_environment(self):
        with mock.patch.object(
            otp_delivery, "OTP_DELIVERY_MODE", "demo"
        ), mock.patch.dict(os.environ, {"EDUSHIELD_ENV": "production"}):
            with self.assertRaisesRegex(DeliveryError, "not allowed"):
                otp_delivery.validate_delivery_config()

    def test_production_mode_is_rejected_in_development_environment(self):
        with mock.patch.object(
            otp_delivery, "OTP_DELIVERY_MODE", "production"
        ), mock.patch.dict(os.environ, {"EDUSHIELD_ENV": "development"}):
            with self.assertRaisesRegex(DeliveryError, "not allowed"):
                otp_delivery.validate_delivery_config()


class NotificationNoFallbackTests(unittest.TestCase):
    """Provider failures must not be hidden by a different delivery path."""

    def test_sms_provider_failure_is_propagated(self):
        failing = mock.Mock(side_effect=DeliveryError("2Factor rejected SMS"))
        with mock.patch.object(
            notifications, "_otp_delivery",
            return_value=("production", mock.Mock(), failing),
        ):
            with self.assertRaisesRegex(DeliveryError, "2Factor rejected"):
                notifications.send_sms(
                    "+919876543210",
                    notifications.sms_parent_code_text("123456"),
                )

        failing.assert_called_once()
        self.assertEqual(failing.call_args.args[1], "123456")

    def test_sms_without_otp_is_refused(self):
        with self.assertRaisesRegex(DeliveryError, "does not contain"):
            notifications.send_sms("+919876543210", "No code here")

    def test_brevo_failure_is_not_retried_over_smtp(self):
        failing = mock.Mock(side_effect=DeliveryError("Brevo rejected email"))
        with mock.patch.dict(
            os.environ, {"BREVO_API_KEY": "test-brevo-key"}
        ), mock.patch.object(
            notifications, "_otp_delivery",
            return_value=("production", failing, mock.Mock()),
        ), mock.patch("smtplib.SMTP") as smtp:
            with self.assertRaisesRegex(DeliveryError, "Brevo rejected"):
                notifications.send_email(
                    "parent@example.test", "subject", "body"
                )
            smtp.assert_not_called()

    def test_demo_email_never_uses_smtp(self):
        demo_email = mock.Mock(return_value={"demo_only": True})
        with mock.patch.object(
            notifications, "_otp_delivery",
            return_value=("demo", demo_email, mock.Mock()),
        ), mock.patch.dict(
            os.environ,
            {
                "BREVO_API_KEY": "",
                "BREVO_APIKEY": "",
                "EDUSHIELD_EMAIL": "sender@example.test",
                "EDUSHIELD_EMAIL_PASSWORD": "test-password",
            },
        ), mock.patch("smtplib.SMTP") as smtp:
            notifications.send_email(
                "parent@example.test", "subject", "body"
            )

        demo_email.assert_called_once()
        smtp.assert_not_called()

    def test_production_email_requires_brevo(self):
        with mock.patch.dict(
            os.environ, {"BREVO_API_KEY": "", "BREVO_APIKEY": ""}
        ), mock.patch.object(
            notifications, "_otp_delivery",
            return_value=("production", mock.Mock(), mock.Mock()),
        ):
            with self.assertRaisesRegex(DeliveryError, "Brevo is not configured"):
                notifications.send_email(
                    "parent@example.test", "subject", "body"
                )


if __name__ == "__main__":
    unittest.main()
