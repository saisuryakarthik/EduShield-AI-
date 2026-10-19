"""
Dual-channel OTP helpers for phone-number-change verification.

Pure functions only: no database and no network access, so the security
logic can be unit-tested in isolation.

Design rules:
    * The SMS code and the email code are generated independently.
    * Only keyed hashes of the codes are stored, never the codes.
    * A code's hash is bound to (request_id, channel), so an SMS code can
      never verify the email channel and vice versa.
    * Codes are generated with the `secrets` module, not `random`.
"""

import hashlib
import hmac
import os
import re
import secrets


OTP_LENGTH = 6
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 3
PARENT_LINK_TTL_MINUTES = 15

CHANNELS = ("SMS", "EMAIL")

_OTP_FORMAT = re.compile(r"\d{%d}" % OTP_LENGTH)

_PEPPER_ENV = "EDUSHIELD_OTP_PEPPER"


def get_otp_pepper() -> bytes:
    """
    Secret key used to key the OTP hashes.

    Without this secret, a leaked database alone is not enough to
    brute-force the 6-digit codes.
    """

    pepper = os.getenv(_PEPPER_ENV)

    if not pepper:
        raise RuntimeError(
            f"{_PEPPER_ENV} must be set. It keys the OTP hashes."
        )

    return pepper.encode("utf-8")


def generate_otp() -> str:
    """Return a cryptographically random zero-padded numeric code."""

    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def hash_otp(request_id: str, channel: str, code: str) -> str:
    """Keyed hash of a code, bound to its request and channel."""

    message = f"{request_id}:{channel}:{code}".encode("utf-8")

    return hmac.new(
        get_otp_pepper(),
        message,
        hashlib.sha256
    ).hexdigest()


def otp_matches(
    request_id: str,
    channel: str,
    code: str,
    stored_hash
) -> bool:
    """Constant-time comparison of a submitted code against its stored hash."""

    if not stored_hash:
        return False

    return hmac.compare_digest(
        hash_otp(request_id, channel, code),
        stored_hash
    )


def is_valid_otp_format(code) -> bool:
    return bool(_OTP_FORMAT.fullmatch(str(code or "").strip()))


def generate_link_token() -> str:
    """Random token for the parent verification link."""

    return secrets.token_urlsafe(32)


def hash_link_token(token: str) -> str:
    """Only the SHA-256 of the link token is stored."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def compute_auth_status(sms_verified: bool, email_verified: bool) -> str:
    """
    Backend-side authentication rule.

    VERIFIED only when BOTH independent OTPs are verified.
    Expiry, lockout and one-time use are enforced per OTP row before
    this is ever called, so the frontend never decides this.
    """

    if sms_verified and email_verified:
        return "VERIFIED"

    return "PENDING"


def normalize_phone_e164(raw, default_country_code: str = "+91"):
    """
    Convert a phone number to E.164 form.

    Returns None when the number cannot be interpreted.
    """

    text = str(raw or "").strip()
    digits = re.sub(r"\D", "", text)

    if text.startswith("+"):
        return f"+{digits}" if 8 <= len(digits) <= 15 else None

    cc_digits = default_country_code.lstrip("+")

    if len(digits) == 10:
        return f"+{cc_digits}{digits}"

    if (
        len(digits) == len(cc_digits) + 10
        and digits.startswith(cc_digits)
    ):
        return f"+{digits}"

    return None


def mask_phone(e164) -> str:
    """'+919876504821' -> '+91 ******4821'."""

    digits = re.sub(r"\D", "", str(e164 or ""))

    if len(digits) < 4:
        return "****"

    return f"+{digits[:2]} ******{digits[-4:]}"


def mask_email(email) -> str:
    """'parent@gmail.com' -> 'pa****@gmail.com'."""

    text = str(email or "")

    if "@" not in text:
        return "****"

    local, domain = text.split("@", 1)

    visible = local[:2] if len(local) > 2 else local[:1]

    return f"{visible}****@{domain}"
