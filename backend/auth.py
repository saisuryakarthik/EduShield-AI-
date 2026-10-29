from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
import logging
import os
import uuid
from config import JWT_SECRET
from functools import wraps
from flask import request, jsonify

import revocation


logger = logging.getLogger("edushield.auth")


# Token lifetime. Short enough to limit the damage of a leaked token,
# long enough not to be disruptive. Override with EDUSHIELD_TOKEN_TTL_MINUTES.
TOKEN_TTL_MINUTES = int(os.getenv("EDUSHIELD_TOKEN_TTL_MINUTES", "60"))


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def generate_token(user_id: str, role: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)

    payload = {
        "user_id": user_id,
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=TOKEN_TTL_MINUTES),
    }

    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def revoke_token(payload, reason="logout") -> bool:
    """
    Persist a decoded token's revocation.

    The revocation is written to the database, so it survives an
    application restart and is shared by every worker of a multi-process
    server. Only the token identifier is stored, never the token
    itself.
    """

    jti = (payload or {}).get("jti")
    user_id = (payload or {}).get("user_id")

    if not jti or not user_id:
        return False

    expires_at = (payload or {}).get("exp")

    if expires_at is None:
        expires_at = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=TOKEN_TTL_MINUTES)
        )

    revoked = revocation.revoke(
        jti,
        user_id,
        expires_at,
        reason=reason
    )

    if revoked:
        # Opportunistic cleanup: rows for tokens that have already
        # expired can never affect an access decision.
        revocation.cleanup_expired()

    return revoked


def is_token_revoked(payload) -> bool:
    """
    True when the token has been revoked.

    Raises revocation.RevocationUnavailable when the store cannot be
    read, so the caller can fail closed.
    """

    jti = (payload or {}).get("jti")

    if not jti:
        # Legacy tokens issued before jti existed cannot be revoked.
        return False

    return revocation.is_revoked(jti)


def require_auth(allowed_roles=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")

            if not auth_header.startswith("Bearer "):
                return jsonify({
                    "success": False,
                    "message": "Missing or invalid Authorization header"
                }), 401

            token = auth_header.split(" ", 1)[1]
            payload = decode_token(token)

            if payload is None:
                return jsonify({
                    "success": False,
                    "message": "Invalid or expired token"
                }), 401

            try:
                revoked = is_token_revoked(payload)
            except revocation.RevocationUnavailable:
                # The revocation state could not be read. The token is
                # NOT accepted: an unverifiable token never passes.
                logger.exception(
                    "Revocation store unavailable; refusing the request"
                )

                return jsonify({
                    "success": False,
                    "message": (
                        "Authentication is temporarily unavailable. "
                        "Please try again."
                    )
                }), 503

            if revoked:
                return jsonify({
                    "success": False,
                    "message": "Invalid or expired token"
                }), 401

            if allowed_roles and payload.get("role") not in allowed_roles:
                return jsonify({
                    "success": False,
                    "message": "You don't have permission to access this resource"
                }), 403

            request.user = payload
            return f(*args, **kwargs)

        return wrapper
    return decorator
