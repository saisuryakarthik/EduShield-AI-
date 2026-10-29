"""
Outbound notifications: email (Brevo in production, demo inbox in demo
mode) and SMS (2Factor in production, demo provider in demo mode).

Nothing in this module logs or returns OTP codes. Provider failures are
propagated as DeliveryError; they are never silently replaced by a
different delivery path, and demo mode never contacts a real provider.
"""

import os
import re


class DeliveryError(RuntimeError):
    """Raised when a notification cannot be delivered."""


def _otp_delivery():
    """
    Import the delivery layer lazily.

    otp_delivery imports DeliveryError from this module, so a module-level
    import here would create a circular import and silently disable the
    provider layer.
    """

    from otp_delivery import (
        OTP_DELIVERY_MODE,
        deliver_email_otp,
        deliver_sms_otp,
    )

    return OTP_DELIVERY_MODE, deliver_email_otp, deliver_sms_otp


def _extract_sms_otp(text):
    match = re.search(
        r"(?:verification code is|code is|verification code:)\s*(\d{6})",
        str(text or ""),
        re.IGNORECASE,
    )
    return match.group(1) if match else None


# ============================================================
# EMAIL
# ============================================================

def send_email(to_address, subject, body, html=None):
    if not to_address:
        raise DeliveryError("No recipient email address is registered.")

    mode, deliver_email_otp, _ = _otp_delivery()

    if mode not in ("demo", "production"):
        raise DeliveryError("Invalid OTP_DELIVERY_MODE.")

    if mode == "production" and not (
        os.getenv("BREVO_API_KEY") or os.getenv("BREVO_APIKEY")
    ):
        raise DeliveryError(
            "Brevo is not configured. Set BREVO_API_KEY and "
            "BREVO_SENDER_EMAIL for production email delivery."
        )

    try:
        deliver_email_otp(to_address, subject, body, html=html)
    except DeliveryError:
        raise
    except Exception as exc:
        label = "Demo" if mode == "demo" else "Brevo"
        raise DeliveryError(
            f"{label} delivery failed: {type(exc).__name__}"
        ) from exc


# ============================================================
# SMS
# ============================================================

def send_sms(to_e164, text, request_id=None):
    code = _extract_sms_otp(text)

    if not code:
        raise DeliveryError("SMS message does not contain a 6-digit OTP.")

    mode, _, deliver_sms_otp = _otp_delivery()

    # The configured provider is authoritative. A provider failure must be
    # visible to the caller, never replaced by console/Twilio fallback.
    try:
        return deliver_sms_otp(to_e164, code, request_id=request_id)
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError(
            f"{mode.capitalize()} SMS delivery failed: {type(exc).__name__}"
        ) from exc


# ============================================================
# MESSAGE TEMPLATES
# ============================================================

def sms_parent_code_text(code):
    return (
        f"EduShield AI: Your parent verification code is {code}. "
        "It expires in 5 minutes. Never share this code. "
        "If you did not expect this, do not enter it."
    )


def email_parent_verification_body(
    student_name,
    new_phone_masked,
    verify_url,
    email_code
):
    return f"""EduShield AI - Verification Required

A phone-number change request has been initiated for the student account of:

    {student_name}

New number requested: {new_phone_masked}

To confirm this change, open the link below and enter the code
that was sent to you by email:

    {verify_url}

Your email verification code: {email_code}

This code expires in 5 minutes. The link expires in 15 minutes.

SECURITY WARNING
Never share this code with anyone, including people claiming to be from
the university. If you did NOT request this change, open the link and
choose "This wasn't me". Do not enter the code.

    EduShield AI
"""


def email_parent_verification_html(
    student_name,
    new_phone_masked,
    verify_url,
    email_code
):
    """HTML alternative for the parent verification email.

    Keeps the link tappable and unwrapped on mobile mail apps.
    """

    from html import escape

    safe_name = escape(str(student_name))
    safe_phone = escape(str(new_phone_masked))
    safe_url = escape(str(verify_url), quote=True)
    safe_code = escape(str(email_code))

    return f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;color:#1f2933;">
  <div style="max-width:560px;margin:0 auto;padding:24px;">
    <div style="background:#0f2a44;color:#ffffff;padding:20px 24px;border-radius:8px 8px 0 0;">
      <h1 style="margin:0;font-size:18px;">EduShield AI &mdash; Verification Required</h1>
    </div>
    <div style="background:#ffffff;padding:24px;border-radius:0 0 8px 8px;">
      <p style="margin:0 0 12px;">A phone-number change request has been initiated for the student account of <strong>{safe_name}</strong>.</p>
      <p style="margin:0 0 20px;">New number requested: <strong>{safe_phone}</strong></p>

      <p style="margin:0 0 12px;">To confirm this change, tap the button below and enter the code that was sent to you by email.</p>

      <p style="margin:0 0 24px;">
        <a href="{safe_url}"
           style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:bold;">
          Open verification page
        </a>
      </p>

      <p style="margin:0 0 8px;">Or paste this address into your browser:</p>
      <p style="margin:0 0 24px;word-break:break-all;">
        <a href="{safe_url}" style="color:#2563eb;">{safe_url}</a>
      </p>

      <p style="margin:0 0 24px;font-size:18px;">
        Email verification code:
        <strong style="letter-spacing:3px;">{safe_code}</strong>
      </p>

      <p style="margin:0 0 12px;color:#52606d;font-size:13px;">This code expires in 5 minutes. The link expires in 15 minutes.</p>

      <div style="border-top:1px solid #e4e7eb;margin:20px 0;padding-top:16px;color:#52606d;font-size:13px;">
        <p style="margin:0 0 8px;"><strong>Security warning:</strong> never share this code with anyone, including people claiming to be from the university.</p>
        <p style="margin:0;">If you did NOT request this change, open the link and choose &ldquo;This wasn't me&rdquo;. Do not enter the code.</p>
      </div>

      <p style="margin:20px 0 0;color:#52606d;font-size:13px;">&mdash; EduShield AI</p>
    </div>
  </div>
</body>
</html>
"""


def email_mentor_new_request(student_name, request_id):
    return f"""EduShield AI - New phone-change request

Student: {student_name}
Request: {request_id}
Status: Awaiting parent verification (SMS + email)

You will be notified again when the parent has completed verification.

EduShield AI
"""


def email_mentor_verification_complete(student_name, request_id):
    return f"""EduShield AI - Parent verification completed

Student: {student_name}
Request: {request_id}

Both parent verification codes (SMS and email) were confirmed.
The request is now ready for your review.

EduShield AI
"""


def email_mentor_security_hold(student_name, request_id):
    return f"""EduShield AI - SECURITY HOLD

Student: {student_name}
Request: {request_id}

The parent reported "This wasn't me". This request is on security hold
and cannot be approved. You may reject it.

EduShield AI
"""


def email_mentor_ai_unavailable(student_name, request_id):
    return f"""EduShield AI - Risk assessment temporarily unavailable

Student: {student_name}
Request: {request_id}

Both parent verification codes (SMS and email) were confirmed, but the
automated risk assessment could not be produced right now.

The request cannot be approved while the assessment is missing. It stays
blocked until an administrator retries the assessment successfully. You may
reject the request in the meantime.

EduShield AI
"""


def email_decision(student_name, request_id, decision, reason=None):
    outcome = "approved" if decision == "APPROVED" else "rejected"

    reason_line = f"\nReason: {reason}\n" if reason else ""

    return f"""EduShield AI - Phone-number change request {outcome}

Student: {student_name}
Request: {request_id}
Result: The phone-number change request was {outcome}.
{reason_line}
EduShield AI
"""


def email_student_security_hold(student_name, request_id):
    return f"""EduShield AI - Security hold on your phone-change request

Hello {student_name},

Request {request_id} was placed on security hold after a parent reported
that the change was not authorised. Your mentor has been notified.
If this was not you, please contact your mentor immediately.

EduShield AI
"""


def email_account_activation_body(name, code):
    return f"""EduShield AI - Activate your account

Hello {name},

Your institution has created an EduShield AI account for you. Use the
code below to set your password and activate it:

    {code}

This code expires in 5 minutes. If you did not expect this, ignore this
email and contact your institution's administrator.

SECURITY WARNING
Never share this code with anyone, including people claiming to be from
the university. EduShield AI staff will never ask you for this code.

EduShield AI
"""


# ============================================================
# IN-APP NOTIFICATION MESSAGES
#
# These strings are shown inside the app inbox. They intentionally carry
# no OTP codes, link tokens, hashes or parent phone numbers. Keep them
# short: the inbox column is VARCHAR(500).
# ============================================================

def inapp_parent_verified(student_name, request_id):
    return (
        f"Parent verification completed for {student_name} "
        f"(request {request_id}). It is ready for your review."
    )


def inapp_mentor_notified(student_name, request_id):
    return (
        f"{student_name} asked you to review phone-change request "
        f"{request_id}."
    )


def inapp_security_hold(student_name, request_id):
    return (
        f"SECURITY HOLD: a parent reported that request {request_id} "
        f"for {student_name} was not authorised. It can only be rejected."
    )


def inapp_request_cancelled(student_name, request_id):
    return (
        f"{student_name} cancelled phone-change request {request_id} "
        f"after asking you to review it."
    )


def inapp_ai_unavailable(student_name, request_id):
    return (
        f"Parent verification is complete for {student_name} "
        f"(request {request_id}), but the risk assessment is temporarily "
        f"unavailable. The request cannot be approved until it is "
        f"retried successfully."
    )


def email_notify_mentor_request(student_name, request_id, dashboard_url):
    return f"""EduShield AI - Review requested

{student_name} has asked you to review this phone-change request:

    Request: {request_id}

Open your mentor dashboard to review it:

    {dashboard_url}

EduShield AI
"""
