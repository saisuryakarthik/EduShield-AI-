"""
OTP delivery abstraction/provider interface for EduShield AI.

Supports:
- DEMO mode: DemoSMSProvider/DemoEmailProvider simulate delivery; no real provider
- PRODUCTION mode: SMS via 2Factor, email via Brevo

Critical: Providers only DELIVER already-generated OTPs. They must NOT generate OTPs.
Raw OTPs are never logged in normal logs and never stored in DB by this module.
"""

import os
import re
import time
from typing import Dict, Any, Optional
from urllib.parse import quote

import requests


from config import (
    OTP_DELIVERY_MODE,
    TWOFACTOR_API_KEY,
    TWOFACTOR_TEMPLATE_NAME,
    BREVO_API_KEY,
    BREVO_SENDER_EMAIL,
    BREVO_SENDER_NAME,
)
from notifications import DeliveryError


# In-memory demo inboxes (DEMO ONLY). Never exposed unauthenticated.
_DEMO_SMS_INBOX = []
_DEMO_EMAIL_INBOX = []


def _json_body(response):
    """Return the decoded JSON body, or None for an empty/non-JSON reply."""

    try:
        return response.json()
    except ValueError:
        return None


def _redact(value, *secrets) -> str:
    """Bound and scrub provider error text before it is logged or raised."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()

    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "<redacted>")

    return text[:300]


def _response_detail(response, *secrets) -> str:
    payload = _json_body(response)

    if isinstance(payload, dict):
        parts = [
            f"{key}={payload[key]}"
            for key in ("code", "message", "error", "Status", "Details")
            if payload.get(key) not in (None, "")
        ]
        if parts:
            return _redact("; ".join(parts), *secrets)

    return _redact(getattr(response, "text", ""), *secrets)


class DemoSMSProvider:
    """Clearly named DemoSMSProvider - simulates successful SMS delivery."""

    def send_sms(self, to_e164: str, code: str, request_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        entry = {
            "request_id": request_id,
            "to": to_e164,
            "code": code,
            "timestamp": time.time(),
            "channel": "SMS",
            "mode": "DEMO_ONLY",
        }
        _DEMO_SMS_INBOX.append(entry)
        print("[DEMO ONLY SMS] Simulated delivery - OTP available via demo inbox (not logged)", flush=True)
        return {"success": True, "provider": "demo_sms", "demo_only": True}


def get_demo_sms_inbox() -> list:
    return list(_DEMO_SMS_INBOX)


def clear_demo_sms_inbox():
    global _DEMO_SMS_INBOX
    _DEMO_SMS_INBOX = []


class DemoEmailProvider:
    """DEMO ONLY: record email content without contacting an external provider."""

    def send_email(self, to_address: str, subject: str, body: str, html: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        entry = {
            "to": to_address,
            "subject": subject,
            "body": body,
            "html": html,
            "timestamp": time.time(),
            "channel": "EMAIL",
            "mode": "DEMO_ONLY",
        }
        _DEMO_EMAIL_INBOX.append(entry)
        print("[DEMO ONLY EMAIL] Simulated delivery - content available via demo inbox (not logged)", flush=True)
        return {"success": True, "provider": "demo_email", "demo_only": True}


def get_demo_email_inbox() -> list:
    return list(_DEMO_EMAIL_INBOX)


def clear_demo_email_inbox():
    global _DEMO_EMAIL_INBOX
    _DEMO_EMAIL_INBOX = []


class TwoFactorProvider:
    """Production 2Factor SMS provider."""

    def send_sms(self, to_e164: str, code: str, **kwargs) -> Dict[str, Any]:
        api_key = TWOFACTOR_API_KEY
        if not api_key:
            raise DeliveryError("2Factor API key not configured. Set TWOFACTOR_API_KEY.")

        phone = re.sub(r"\D", "", str(to_e164 or ""))
        if not phone:
            raise DeliveryError("2Factor recipient phone number is invalid.")

        otp = str(code or "").strip()
        if not re.fullmatch(r"\d{6}", otp):
            raise DeliveryError("2Factor requires a 6-digit OTP.")

        url = (
            "https://2factor.in/API/V1/"
            f"{quote(api_key, safe='')}/SMS/{quote(phone, safe='')}/"
            f"{quote(otp, safe='')}"
        )

        # 2Factor Custom OTP endpoint: the optional template name lets the
        # account use its approved DLT template without changing our code.
        if TWOFACTOR_TEMPLATE_NAME:
            url += f"/{quote(TWOFACTOR_TEMPLATE_NAME, safe='')}"

        try:
            response = requests.post(url, timeout=15)
        except requests.RequestException as exc:
            detail = _redact(exc, api_key, phone, otp)
            raise DeliveryError(f"2Factor request failed: {detail}") from exc

        payload = _json_body(response) or {}
        status = str(payload.get("Status", "")).strip()
        details = payload.get("Details")

        if response.status_code >= 300 or status.lower() != "success":
            detail = _response_detail(response, api_key, phone, otp)
            raise DeliveryError(
                "2Factor rejected SMS "
                f"(HTTP {response.status_code}, status={status or 'unknown'}): "
                f"{detail or 'no detail returned'}"
            )

        return {
            "success": True,
            "provider": "2factor",
            "session_id": str(details) if details else None,
        }


class BrevoEmailProvider:
    """Brevo Transactional Email API provider."""

    def send_email(self, to_address: str, subject: str, body: str, html: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        api_key = BREVO_API_KEY
        if not api_key:
            raise DeliveryError("Brevo API key not configured. Set BREVO_API_KEY.")

        sender_email = BREVO_SENDER_EMAIL or os.getenv("EDUSHIELD_EMAIL")
        sender_name = BREVO_SENDER_NAME

        if not sender_email:
            raise DeliveryError("Brevo sender email not configured.")

        payload = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": to_address}],
            "subject": subject,
            "textContent": body,
        }
        if html:
            payload["htmlContent"] = html

        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }

        try:
            response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:
            detail = _redact(exc, api_key, to_address)
            raise DeliveryError(f"Brevo request failed: {detail}") from exc

        if response.status_code >= 300:
            detail = _response_detail(response, api_key, to_address)
            raise DeliveryError(
                f"Brevo rejected email (HTTP {response.status_code}): "
                f"{detail or 'no detail returned'}"
            )

        body = _json_body(response) or {}
        return {
            "success": True,
            "provider": "brevo",
            "message_id": body.get("messageId"),
        }


demo_sms_provider = DemoSMSProvider()
demo_email_provider = DemoEmailProvider()
twofactor_provider = TwoFactorProvider()
brevo_email_provider = BrevoEmailProvider()


def get_sms_provider():
    mode = OTP_DELIVERY_MODE
    if mode == "demo":
        return demo_sms_provider
    elif mode == "production":
        return twofactor_provider
    else:
        raise RuntimeError(f"Invalid OTP_DELIVERY_MODE: {mode}")


def get_email_provider():
    mode = OTP_DELIVERY_MODE
    if mode == "demo":
        return demo_email_provider
    elif mode == "production":
        return brevo_email_provider
    else:
        raise RuntimeError(f"Invalid OTP_DELIVERY_MODE: {mode}")


def validate_delivery_config():
    """
    Fail before serving traffic when delivery configuration is unsafe.

    Only names, never values, are reported. Demo mode must use the
    in-memory demo providers and production mode must be explicitly
    enabled outside development/test environments.
    """

    mode = OTP_DELIVERY_MODE

    if mode == "demo":
        environment = (os.getenv("EDUSHIELD_ENV") or "").strip().lower()

        if environment in ("production", "prod"):
            raise DeliveryError(
                "OTP_DELIVERY_MODE=demo is not allowed when "
                f"EDUSHIELD_ENV={environment}. Configure production "
                "providers or run in a non-production environment."
            )

        if not isinstance(get_sms_provider(), DemoSMSProvider):
            raise DeliveryError("Demo SMS provider is not the demo provider.")
        if not isinstance(get_email_provider(), DemoEmailProvider):
            raise DeliveryError("Demo email provider is not the demo provider.")
        return True

    if mode != "production":
        raise DeliveryError("OTP_DELIVERY_MODE must be one of: demo, production")

    environment = (os.getenv("EDUSHIELD_ENV") or "").strip().lower()

    if environment in ("demo", "development", "dev", "test", "testing", "local"):
        raise DeliveryError(
            "OTP_DELIVERY_MODE=production is not allowed when "
            f"EDUSHIELD_ENV={environment}."
        )

    missing = []

    if not TWOFACTOR_API_KEY:
        missing.append("TWOFACTOR_API_KEY")
    if not BREVO_API_KEY:
        missing.append("BREVO_API_KEY")
    if not (BREVO_SENDER_EMAIL or os.getenv("EDUSHIELD_EMAIL")):
        missing.append("BREVO_SENDER_EMAIL")

    if missing:
        raise DeliveryError(
            "Production OTP delivery is not configured. Missing: "
            + ", ".join(missing)
        )

    if not isinstance(get_sms_provider(), TwoFactorProvider):
        raise DeliveryError("Production SMS provider is not 2Factor.")
    if not isinstance(get_email_provider(), BrevoEmailProvider):
        raise DeliveryError("Production email provider is not Brevo.")

    return True


def deliver_sms_otp(to_e164: str, code: str, request_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    provider = get_sms_provider()
    return provider.send_sms(to_e164, code, request_id=request_id, **kwargs)


def deliver_email_otp(to_address: str, subject: str, body: str, html: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    provider = get_email_provider()
    return provider.send_email(to_address, subject, body, html=html, **kwargs)
