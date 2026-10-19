from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
import os
import threading
import uuid
from config import JWT_SECRET
from functools import wraps
from flask import request, jsonify


# Token lifetime. Short enough to limit the damage of a leaked token,
# long enough not to be disruptive. Override with EDUSHIELD_TOKEN_TTL_MINUTES.
TOKEN_TTL_MINUTES = int(os.getenv("EDUSHIELD_TOKEN_TTL_MINUTES", "60"))


# In-process revocation list, keyed by the token's `jti`.
#
# LIMITATION: this is per-process and lost on restart, so it is a
# best-effort revocation until a shared store (or a DB column) is added.
# It is still strictly better than cookie-only logout.
_revoked_lock = threading.Lock()
_revoked_jtis = set()


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


def revoke_token(payload) -> bool:
    """Add a decoded token's jti to the revocation list."""

    jti = (payload or {}).get("jti")

    if not jti:
        return False

    with _revoked_lock:
        _revoked_jtis.add(jti)

    return True


def is_token_revoked(payload) -> bool:
    """True when the token has been revoked."""

    jti = (payload or {}).get("jti")

    if not jti:
        # Legacy tokens issued before jti existed cannot be revoked.
        return False

    with _revoked_lock:
        return jti in _revoked_jtis


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

            if is_token_revoked(payload):
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
