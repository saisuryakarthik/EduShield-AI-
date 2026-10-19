"""
Outbound notifications: email (SMTP) and SMS (provider behind one function).

Nothing in this module logs OTP codes in production. The `console`
SMS provider prints codes so developers can test locally, and it refuses
to run when EDUSHIELD_ENV=production.
"""

import os
import smtplib
from email.message import EmailMessage

import requests


SMS_PROVIDER_ENV = "EDUSHIELD_SMS_PROVIDER"   # twilio | console | disabled
APP_ENV_VAR = "EDUSHIELD_ENV"                 # development | production


class DeliveryError(RuntimeError):
    """Raised when a notification cannot be delivered."""


# ============================================================
# EMAIL
# ============================================================

def send_email(to_address, subject, body):
    if not to_address:
        raise DeliveryError("No recipient email address is registered.")

    sender = os.getenv("EDUSHIELD_EMAIL")
    password = os.getenv("EDUSHIELD_EMAIL_PASSWORD")

    if not sender or not password:
        raise DeliveryError(
            "Email is not configured. Set EDUSHIELD_EMAIL and "
            "EDUSHIELD_EMAIL_PASSWORD."
        )

    host = os.getenv("EDUSHIELD_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("EDUSHIELD_SMTP_PORT", "587"))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"EduShield AI <{sender}>"
    message["To"] = to_address
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)


# ============================================================
# SMS
# ============================================================

def send_sms(to_e164, text):
    provider = os.getenv(SMS_PROVIDER_ENV, "disabled").strip().lower()

    if provider == "twilio":
        return _send_twilio(to_e164, text)

    if provider == "console":
        if os.getenv(APP_ENV_VAR, "development").lower() == "production":
            raise DeliveryError(
                "The console SMS provider is not allowed in production."
            )

        # DEVELOPMENT ONLY: lets a developer read the code locally.
        print(f"[DEV ONLY SMS] to={to_e164} text={text}", flush=True)
        return

    raise DeliveryError(
        "SMS provider is not configured. "
        f"Set {SMS_PROVIDER_ENV} to 'twilio' (production) or "
        "'console' (local development)."
    )


def _send_twilio(to_e164, text):
    """
    Send through Twilio's REST API. No SDK needed.

    Indian mobile numbers need DLT registration (sender ID and template)
    before messages are delivered. Set up DLT before go-live.
    """

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")

    if not account_sid or not auth_token or not from_number:
        raise DeliveryError(
            "Twilio is not configured. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER."
        )

    response = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
        data={
            "To": to_e164,
            "From": from_number,
            "Body": text,
        },
        auth=(account_sid, auth_token),
        timeout=15,
    )

    if response.status_code >= 300:
        raise DeliveryError(
            f"SMS provider returned HTTP {response.status_code}."
        )


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
