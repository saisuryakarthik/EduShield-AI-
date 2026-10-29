from flask import Flask, jsonify, request, render_template, Response
from flask_cors import CORS
import datetime
import json
import time
import uuid
import math
import re
import os
from dotenv import load_dotenv
load_dotenv()

from ai.models.predict import predict_risk
from ai.models.predict import FEATURES as MODEL_FEATURES
from ai.models.predict import model as RISK_MODEL
from ai.models.predict import MODEL_VERSION
import mysql.connector

import anomaly
import explain
import model_registry
import recovery
import reports
import revocation
import timeline

from auth import (
    generate_token,
    hash_password,
    require_auth,
    revoke_token,
    verify_password,
)
from config import (
    ACTIVATION_MAX_ATTEMPTS,
    ACTIVATION_OTP_EXPIRY_MINUTES,
    ACTIVATION_RESEND_COOLDOWN_SECONDS,
    DB_CONFIG,
)
from ratelimit import limiter
from otp import (
    CHANNELS,
    OTP_LENGTH,
    OTP_MAX_ATTEMPTS,
    OTP_TTL_MINUTES,
    PARENT_LINK_TTL_MINUTES,
    compute_auth_status,
    generate_link_token,
    generate_otp,
    get_otp_pepper,
    hash_link_token,
    hash_otp,
    is_valid_otp_format,
    mask_email,
    mask_phone,
    normalize_phone_e164,
    otp_matches,
)
from notifications import (
    DeliveryError,
    email_account_activation_body,
    email_decision,
    email_mentor_ai_unavailable,
    email_mentor_new_request,
    email_mentor_security_hold,
    email_mentor_verification_complete,
    email_notify_mentor_request,
    email_parent_verification_body,
    email_parent_verification_html,
    email_student_security_hold,
    inapp_ai_unavailable,
    inapp_mentor_notified,
    inapp_parent_verified,
    inapp_request_cancelled,
    inapp_security_hold,
    send_email,
    send_sms,
    sms_parent_code_text,
)
try:
    from otp_delivery import (
        get_demo_sms_inbox,
        clear_demo_sms_inbox,
        get_demo_email_inbox,
        clear_demo_email_inbox,
        OTP_DELIVERY_MODE,
    )
except Exception:
    get_demo_sms_inbox = None
    clear_demo_sms_inbox = None
    get_demo_email_inbox = None
    clear_demo_email_inbox = None
    OTP_DELIVERY_MODE = os.getenv("OTP_DELIVERY_MODE", "demo").strip().lower()


app = Flask(
    __name__,
    template_folder="../frontend-flask/templates"
)


def _allowed_origins():
    """
    Browser origins allowed to call this API.

    The frontend calls the API server-to-server (no CORS needed) and the
    parent verification page is served by this same application, so
    cross-origin browser access is opt-in through the environment.
    """

    raw = os.getenv("EDUSHIELD_ALLOWED_ORIGINS", "")

    origins = [
        origin.strip()
        for origin in raw.split(",")
        if origin.strip()
    ]

    if origins:
        return origins

    return [
        "http://127.0.0.1:5002",
        "http://localhost:5002",
    ]


CORS(
    app,
    origins=_allowed_origins(),
    supports_credentials=False,
)


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

RISK_THRESHOLD = 50

# Phase 1: account activation.
ACTIVATION_CHANNEL = "ACTIVATION"
ACTIVATION_MIN_PASSWORD_LENGTH = 8

# Fails at startup if EDUSHIELD_OTP_PEPPER is not configured.
get_otp_pepper()


# -------------------------------------------------------------------
# Rate limiting
# -------------------------------------------------------------------

def get_client_ip():
    """
    Best-effort client IP for rate limiting.

    request.remote_addr is used directly. Proxy headers are NOT trusted
    by default because they are client-controllable unless a trusted
    reverse proxy is explicitly configured.
    """

    return request.remote_addr or "unknown"


def rate_limit_exceeded(bucket, identity, limit, window_seconds, message):
    """
    Enforce a fixed-window limit.

    Returns a Flask 429 response when the limit is exceeded, otherwise
    None so the caller can continue.
    """

    allowed, retry_after = limiter.allow(
        f"{bucket}:{identity}",
        limit,
        window_seconds
    )

    if allowed:
        return None

    response = jsonify({
        "success": False,
        "message": message
    })

    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)

    return response


# -------------------------------------------------------------------
# Database helpers
# -------------------------------------------------------------------

def get_db():
    return mysql.connector.connect(**DB_CONFIG)


# The token revocation store lives in its own module but must always
# talk to the same database as the rest of the app. The factory is
# registered as a callable (not a connection) so that it resolves
# get_db() at call time.
revocation.set_connection_factory(lambda: get_db())


def close_db(cursor=None, connection=None):
    try:
        if cursor:
            cursor.close()
    finally:
        if connection:
            connection.close()


def serialize_record(record):
    if not record:
        return record

    for key, value in record.items():
        if isinstance(
            value,
            (
                datetime.datetime,
                datetime.date,
                datetime.time
            )
        ):
            record[key] = value.isoformat()

    return record


# -------------------------------------------------------------------
# Mentor assignment helpers
#
# Mentor relationships live in mentor_assignments, not on users. A
# student has at most one active mentor at a time.
# -------------------------------------------------------------------

def get_active_mentor(cursor, student_id):
    """Return the student's active mentor_id, or None."""

    cursor.execute(
        """
        SELECT mentor_id
        FROM mentor_assignments
        WHERE student_id = %s
          AND active = 1
        """,
        (student_id,)
    )

    row = cursor.fetchone()

    return row["mentor_id"] if row else None


def mentor_manages_student(cursor, mentor_id, student_id):
    """True when mentor_id currently has an active assignment to student_id."""

    cursor.execute(
        """
        SELECT 1
        FROM mentor_assignments
        WHERE student_id = %s
          AND mentor_id = %s
          AND active = 1
        """,
        (student_id, mentor_id)
    )

    return cursor.fetchone() is not None


# -------------------------------------------------------------------
# Security event helpers
# -------------------------------------------------------------------

def get_client_device_id():
    """
    Get the application-specific device ID sent by the frontend.

    The application uses a random device ID stored by the frontend.
    We do not perform browser/device fingerprinting.
    """

    device_id = request.headers.get("X-Device-ID", "")

    if not device_id:
        data = request.get_json(silent=True) or {}
        device_id = data.get("device_id", "")

    device_id = str(device_id).strip()

    if len(device_id) > 255:
        device_id = device_id[:255]

    return device_id or None


def get_client_location():
    """
    Get location only when the client explicitly provides it.

    Supported headers:
        X-Client-Latitude
        X-Client-Longitude

    The backend does not silently request GPS information.
    """

    latitude = request.headers.get(
        "X-Client-Latitude"
    )

    longitude = request.headers.get(
        "X-Client-Longitude"
    )

    if latitude is None or longitude is None:

        data = request.get_json(
            silent=True
        ) or {}

        if latitude is None:
            latitude = data.get(
                "latitude"
            )

        if longitude is None:
            longitude = data.get(
                "longitude"
            )

    try:

        if latitude is None or longitude is None:
            return None, None

        latitude = float(latitude)
        longitude = float(longitude)

        if not (-90 <= latitude <= 90):
            return None, None

        if not (-180 <= longitude <= 180):
            return None, None

        return latitude, longitude

    except (TypeError, ValueError):

        return None, None


def log_security_event(
    connection,
    user_id,
    event_type,
    success=True,
    device_id=None,
    latitude=None,
    longitude=None
):
    """
    Store an actual security event.

    Requires the security_events table.
    """

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO security_events
            (
                user_id,
                event_type,
                success,
                device_id,
                ip_address,
                user_agent,
                latitude,
                longitude
            )
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                event_type,
                1 if success else 0,
                device_id,
                request.remote_addr,
                request.headers.get(
                    "User-Agent"
                ),
                latitude,
                longitude
            )
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Location calculation
# -------------------------------------------------------------------

def haversine_distance_km(
    lat1,
    lon1,
    lat2,
    lon2
):
    """
    Calculate geographic distance between two coordinates.
    """

    earth_radius_km = 6371.0

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)

    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return earth_radius_km * c


def calculate_location_deviation(
    connection,
    user_id,
    current_latitude,
    current_longitude
):
    """
    Calculate location deviation using the user's
    historical successful-login locations.

    0.0 = close to previous locations
    1.0 = large deviation

    100 km is used as the normalization ceiling.
    """

    if (
        current_latitude is None
        or current_longitude is None
    ):
        return 0.0

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        cursor.execute(
            """
            SELECT
                latitude,
                longitude
            FROM security_events
            WHERE user_id = %s
              AND event_type = 'LOGIN_SUCCESS'
              AND success = 1
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (user_id,)
        )

        locations = cursor.fetchall()

        if not locations:
            return 0.0

        distances = []

        for location in locations:

            distance = haversine_distance_km(
                current_latitude,
                current_longitude,
                float(location["latitude"]),
                float(location["longitude"])
            )

            distances.append(distance)

        average_distance = (
            sum(distances)
            / len(distances)
        )

        deviation = min(
            average_distance / 100.0,
            1.0
        )

        return round(
            deviation,
            4
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Login time calculation
# -------------------------------------------------------------------

def calculate_login_time_deviation(
    connection,
    user_id
):
    """
    Compare the current login time with the user's
    historical successful-login times.

    Returns:
        0.0 = normal
        1.0 = highly unusual

    If there is no login history, returns 0.0.
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        cursor.execute(
            """
            SELECT created_at
            FROM security_events
            WHERE user_id = %s
              AND event_type = 'LOGIN_SUCCESS'
              AND success = 1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (user_id,)
        )

        events = cursor.fetchall()

        if not events:
            return 0.0

        now = datetime.datetime.now()

        current_minutes = (
            now.hour * 60
            + now.minute
        )

        deviations = []

        for event in events:

            event_time = event["created_at"]

            historical_minutes = (
                event_time.hour * 60
                + event_time.minute
            )

            difference = abs(
                current_minutes
                - historical_minutes
            )

            difference = min(
                difference,
                1440 - difference
            )

            deviations.append(
                difference
            )

        average_difference = (
            sum(deviations)
            / len(deviations)
        )

        deviation = min(
            average_difference / 720.0,
            1.0
        )

        return round(
            deviation,
            4
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Device calculation
# -------------------------------------------------------------------

def get_known_device(
    connection,
    user_id,
    device_id
):
    """
    Determine whether this device has previously
    completed a successful login.

    First/new device:
        0

    Previously used device:
        1
    """

    if not device_id:
        return 0

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT 1
            FROM security_events
            WHERE user_id = %s
              AND event_type = 'LOGIN_SUCCESS'
              AND success = 1
              AND device_id = %s
            LIMIT 1
            """,
            (
                user_id,
                device_id
            )
        )

        return (
            1
            if cursor.fetchone()
            else 0
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Failed login calculation
# -------------------------------------------------------------------

def get_failed_login_count(
    connection,
    user_id
):
    """
    Count actual failed login attempts
    during the previous 24 hours.
    """

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM security_events
            WHERE user_id = %s
              AND event_type = 'LOGIN_FAILURE'
              AND success = 0
              AND created_at >=
                  DATE_SUB(
                      NOW(),
                      INTERVAL 24 HOUR
                  )
            """,
            (user_id,)
        )

        return int(
            cursor.fetchone()[0] or 0
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Password reset calculation
# -------------------------------------------------------------------

def get_recent_password_reset(
    connection,
    user_id
):
    """
    Check whether a successful password reset
    occurred during the previous 24 hours.
    """

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM security_events
            WHERE user_id = %s
              AND event_type = 'PASSWORD_RESET'
              AND success = 1
              AND created_at >=
                  DATE_SUB(
                      NOW(),
                      INTERVAL 24 HOUR
                  )
            """,
            (user_id,)
        )

        return (
            1
            if cursor.fetchone()[0] > 0
            else 0
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# MFA calculation
# -------------------------------------------------------------------

def get_mfa_status(
    connection,
    user_id
):
    """
    Determine MFA status from an actual previous
    successful MFA event.

    The current phone-change OTP is NOT counted here
    because risk is calculated before that OTP is verified.
    """

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM security_events
            WHERE user_id = %s
              AND event_type = 'MFA_SUCCESS'
              AND success = 1
              AND created_at >=
                  DATE_SUB(
                      NOW(),
                      INTERVAL 30 DAY
                  )
            """,
            (user_id,)
        )

        return (
            1
            if cursor.fetchone()[0] > 0
            else 0
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Trust score
# -------------------------------------------------------------------

def get_trust_score(
    connection,
    user_id
):
    """
    Calculate trust score from account history.

    IMPORTANT:
    Trust score is independent from ML risk prediction.
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_requests,

                SUM(
                    CASE
                        WHEN status = 'APPROVED'
                        THEN 1
                        ELSE 0
                    END
                ) AS approved_requests,

                SUM(
                    CASE
                        WHEN status = 'REJECTED'
                        THEN 1
                        ELSE 0
                    END
                ) AS rejected_requests,

                SUM(
                    CASE
                        WHEN auth_status = 'VERIFIED'
                        THEN 1
                        ELSE 0
                    END
                ) AS verified_requests

            FROM phone_change_requests

            WHERE user_id = %s
            """,
            (user_id,)
        )

        history = cursor.fetchone() or {}

        approved_requests = int(
            history.get(
                "approved_requests"
            ) or 0
        )

        rejected_requests = int(
            history.get(
                "rejected_requests"
            ) or 0
        )

        verified_requests = int(
            history.get(
                "verified_requests"
            ) or 0
        )

        trust_score = 80.0

        trust_score += min(
            approved_requests * 3,
            15
        )

        trust_score += min(
            verified_requests,
            5
        )

        trust_score -= min(
            rejected_requests * 5,
            20
        )

        trust_score = max(
            0.0,
            min(
                100.0,
                trust_score
            )
        )

        return round(
            trust_score,
            2
        )

    finally:

        cursor.close()


# -------------------------------------------------------------------
# Risk helpers
# -------------------------------------------------------------------

def determine_risk_level(risk_score):
    """
    Convert ML risk score into display level.
    """

    if risk_score >= RISK_THRESHOLD:
        return "HIGH"

    return "LOW"


def build_risk_factors(
    security_features
):
    """
    Generate human-readable security factors.

    These are rule-based display factors.

    IMPORTANT:
    Trust score is NOT included because trust score
    is independent from ML risk prediction.
    """

    factors = []

    if security_features[
        "known_device"
    ] == 0:

        factors.append(
            "New device detected"
        )

    if security_features[
        "location_deviation"
    ] > 0.6:

        factors.append(
            "Unusual location deviation"
        )

    if security_features[
        "failed_login_count"
    ] > 2:

        factors.append(
            "Multiple failed login attempts"
        )

    if security_features[
        "recent_password_reset"
    ] == 1:

        factors.append(
            "Recent password reset"
        )

    if security_features[
        "mfa_verified"
    ] == 0:

        factors.append(
            "MFA not verified"
        )

    if security_features[
        "phone_change_frequency"
    ] > 2:

        factors.append(
            "Frequent phone changes"
        )

    if security_features[
        "login_time_deviation"
    ] > 0.6:

        factors.append(
            "Unusual login time pattern"
        )

    if not factors:

        factors.append(
            "No elevated security signals detected"
        )

    return factors


# -------------------------------------------------------------------
# Collect security features
# -------------------------------------------------------------------

def collect_security_features(
    connection,
    user_id,
    device_id=None,
    latitude=None,
    longitude=None
):
    """
    Build the security context for the current request.

    Seven values are passed to the ML model.

    Trust score is calculated separately and is NOT
    passed to predict_risk().
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        cursor.execute(
            """
            SELECT COUNT(*) AS phone_change_frequency

            FROM phone_change_requests

            WHERE user_id = %s

              AND requested_at >=
                  DATE_SUB(
                      NOW(),
                      INTERVAL 30 DAY
                  )
            """,
            (user_id,)
        )

        history = cursor.fetchone() or {}

        phone_change_frequency = min(
            int(
                history.get(
                    "phone_change_frequency"
                ) or 0
            ),
            3
        )

    finally:

        cursor.close()

    known_device = get_known_device(
        connection,
        user_id,
        device_id
    )

    failed_login_count = get_failed_login_count(
        connection,
        user_id
    )

    recent_password_reset = get_recent_password_reset(
        connection,
        user_id
    )

    mfa_verified = get_mfa_status(
        connection,
        user_id
    )

    location_deviation = calculate_location_deviation(
        connection,
        user_id,
        latitude,
        longitude
    )

    login_time_deviation = calculate_login_time_deviation(
        connection,
        user_id
    )

    trust_score = get_trust_score(
        connection,
        user_id
    )

    return {

        "known_device":
            known_device,

        "location_deviation":
            location_deviation,

        "failed_login_count":
            failed_login_count,

        "recent_password_reset":
            recent_password_reset,

        "mfa_verified":
            mfa_verified,

        "phone_change_frequency":
            phone_change_frequency,

        "login_time_deviation":
            login_time_deviation,

        "trust_score":
            trust_score
    }


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------

@app.route(
    "/api/health",
    methods=["GET"]
)
def health():

    return jsonify({
        "success": True,
        "message":
            "EduShield AI backend is running"
    })


@app.route(
    "/api/health/ready",
    methods=["GET"]
)
def health_ready():
    """
    Readiness probe: the process is up and MySQL answers a read.

    Unauthenticated so a load balancer can use it. It never returns
    connection details or exception text.
    """

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()

        return jsonify({
            "success": True,
            "status": "ready",
            "database": "reachable"
        }), 200

    except Exception:
        app.logger.warning("Readiness check failed")

        return jsonify({
            "success": False,
            "status": "not_ready",
            "message": "Database unavailable"
        }), 503

    finally:
        close_db(cursor, connection)


@app.route(
    "/api/db-test",
    methods=["GET"]
)
@require_auth()
def db_test():

    # Development/ops utility only. Disabled in production and never
    # exposed without authentication.
    if os.getenv(
        "EDUSHIELD_ENV",
        "development"
    ).lower() == "production":

        return jsonify({
            "success": False,
            "message": "Not found"
        }), 404

    connection = None
    cursor = None

    try:

        connection = get_db()

        cursor = connection.cursor()

        cursor.execute(
            "SELECT DATABASE();"
        )

        database = cursor.fetchone()[0]

        return jsonify({
            "success": True,
            "message":
                "MySQL connection successful",
            "database":
                database
        })

    except Exception:

        app.logger.exception("Database test failed")

        return jsonify({
            "success": False,
            "message":
                "MySQL connection failed"
        }), 500

    finally:

        close_db(
            cursor,
            connection
        )


# -------------------------------------------------------------------
# Authentication
# -------------------------------------------------------------------

@app.route(
    "/api/auth/login",
    methods=["POST"]
)
def login():

    data = request.get_json(
        silent=True
    ) or {}

    email = data.get("email")
    password = data.get("password")

    device_id = get_client_device_id()

    latitude, longitude = (
        get_client_location()
    )

    if not email or not password:

        return jsonify({
            "success": False,
            "message":
                "Email and password are required"
        }), 400

    # Throttle by client IP and by account to slow credential stuffing.
    limited = rate_limit_exceeded(
        "login-ip",
        get_client_ip(),
        20,
        60,
        "Too many login attempts. Please try again later."
    )

    if limited:
        return limited

    limited = rate_limit_exceeded(
        "login-account",
        str(email).strip().lower(),
        10,
        60,
        "Too many login attempts. Please try again later."
    )

    if limited:
        return limited

    connection = None
    cursor = None

    try:

        connection = get_db()

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                user_id,
                name,
                email,
                role,
                account_status,
                password_hash

            FROM users

            WHERE email = %s
            """,
            (email,)
        )

        user = cursor.fetchone()

        if (
            not user
            or not verify_password(
                password,
                user["password_hash"]
            )
        ):

            if user:

                log_security_event(
                    connection,
                    user["user_id"],
                    "LOGIN_FAILURE",
                    success=False,
                    device_id=device_id,
                    latitude=latitude,
                    longitude=longitude
                )

                connection.commit()

            return jsonify({
                "success": False,
                "message":
                    "Invalid email or password"
            }), 401

        # A correct password is not enough: the account must be active.
        # Pending accounts (imported, not yet activated) are refused with
        # a distinct, actionable message.
        if user.get("account_status") != "active":
            return jsonify({
                "success": False,
                "account_status": user.get("account_status"),
                "message":
                    "This account is not active yet. Use your activation "
                    "code from the email to set a password first."
            }), 403

        log_security_event(
            connection,
            user["user_id"],
            "LOGIN_SUCCESS",
            success=True,
            device_id=device_id,
            latitude=latitude,
            longitude=longitude
        )

        connection.commit()

        token = generate_token(
            user["user_id"],
            user["role"]
        )

        return jsonify({
            "success": True,
            "message":
                "Login successful",

            "token":
                token,

            "user": {

                "user_id":
                    user["user_id"],

                "name":
                    user["name"],

                "email":
                    user["email"],

                "role":
                    user["role"]
            }
        })

    except Exception:
        if connection:
            connection.rollback()

        app.logger.exception("Login failed")

        return jsonify({
            "success": False,
            "message":
                "Login failed"
        }), 500

    finally:

        close_db(
            cursor,
            connection
        )

@app.route("/api/auth/me", methods=["GET"])
@require_auth()
def me():
    connection = None
    cursor = None

    try:
        user_id = request.user["user_id"]

        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                user_id,
                name,
                email,
                role,
                phone_number
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user:
            return jsonify({
                "success": False,
                "message": "User not found"
            }), 404

        return jsonify({
            "success": True,
            "user": user
        }), 200

    except Exception:
        app.logger.exception("Failed to fetch user profile")

        return jsonify({
            "success": False,
            "message": "Failed to fetch user profile"
        }), 500

    finally:
        close_db(cursor, connection)


@app.route("/api/auth/logout", methods=["POST"])
@require_auth()
def logout():
    """
    Revoke the caller's current token.

    The revocation is persisted in the database, so the token stays
    revoked across an application restart and across the workers of a
    multi-process server.
    """

    try:
        revoked = revoke_token(request.user, reason="logout")
    except revocation.RevocationUnavailable:
        app.logger.exception("Could not persist the token revocation")

        return jsonify({
            "success": False,
            "message": (
                "Could not revoke the session. Please try again."
            )
        }), 503

    return jsonify({
        "success": True,
        "message": "Logged out",
        "revoked": revoked
    }), 200



# -------------------------------------------------------------------
# Audit helper
# -------------------------------------------------------------------

def write_audit(
    cursor,
    request_id,
    user_id,
    actor,
    action,
    details=None
):
    """
    Append one security/activity event to audit_logs.

    Never pass OTP codes or link tokens in `details`.
    """

    cursor.execute(
        """
        INSERT INTO audit_logs
        (
            request_id,
            user_id,
            actor,
            action,
            details
        )
        VALUES
        (%s, %s, %s, %s, %s)
        """,
        (
            request_id,
            user_id,
            actor,
            action,
            json.dumps(details or {})
        )
    )


def _notify_safely(label, fn, *args, **kwargs):
    """
    Run a notification after the database commit.

    A notification failure must never roll back or fail the security
    decision that already happened, so errors are logged and swallowed.
    """

    try:
        fn(*args, **kwargs)

    except DeliveryError as e:
        print(f"⚠️ {label} not delivered: {e}", flush=True)

    except Exception as e:
        print(f"⚠️ {label} failed: {repr(e)}", flush=True)


# -------------------------------------------------------------------
# In-app notifications
#
# A notification is a durable inbox row addressed to one user. It is
# written inside the same transaction as the event it describes, so the
# inbox can never disagree with the audit trail. Messages are built by
# trusted helpers only and never contain OTP codes, link tokens, hashes
# or parent phone numbers.
# -------------------------------------------------------------------

# Notification types. Kept as constants so tests and UI can rely on them.
NOTIFY_PARENT_VERIFIED = "PARENT_VERIFIED"
NOTIFY_MENTOR_NOTIFIED = "MENTOR_NOTIFIED"
NOTIFY_SECURITY_HOLD = "SECURITY_HOLD"
NOTIFY_REQUEST_CANCELLED = "REQUEST_CANCELLED"
NOTIFY_SECURITY_ALERT = "SECURITY_ALERT"
NOTIFY_STUDENT_REPORT = "STUDENT_REPORT"
NOTIFY_OVERDUE_REMINDER = "OVERDUE_REMINDER"
NOTIFY_ESCALATION = "ESCALATION"
NOTIFY_RECOVERY = "ACCOUNT_RECOVERY"
NOTIFY_AI_UNAVAILABLE = "AI_ASSESSMENT_UNAVAILABLE"


def create_timeline_event(cursor, request_id, event_type, category, title,
                          actor_type=timeline.ACTOR_SYSTEM, actor_id=None,
                          summary=None, details=None):
    """
    Append a timeline event on the caller's transaction.

    Timeline failures must never break the action they describe, so a
    missing table (an older database that has not run migration 005) is
    logged and skipped rather than raised.
    """

    try:
        return timeline.add_event(
            cursor,
            request_id,
            event_type,
            category,
            title,
            actor_type=actor_type,
            actor_id=actor_id,
            summary=summary,
            details=details,
        )
    except mysql.connector.Error as error:
        if error.errno in (1146, 1054):
            app.logger.warning(
                "Timeline unavailable (run migration 005): %s", error
            )
            return None
        raise



def create_notification(cursor, user_id, type, request_id, message):
    """
    Insert one in-app notification for `user_id`.

    Runs on the caller's cursor/transaction so a rolled-back event never
    leaves a notification behind. Returns the new notification_id.
    """

    cursor.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            type,
            request_id,
            message
        )
        VALUES
        (%s, %s, %s, %s)
        """,
        (user_id, type, request_id, message)
    )

    return cursor.lastrowid


def _notify_inbox_safely(cursor, user_id, type, request_id, message):
    """
    Write one in-app notification without ever breaking the action it
    describes.

    A missing inbox table (migration 004 has not been applied yet) is
    logged and skipped. An assessment must never be thrown away because
    a notification could not be stored.
    """

    try:
        return create_notification(
            cursor, user_id, type, request_id, message
        )
    except mysql.connector.Error as error:
        if error.errno not in (1146, 1054):
            raise

        app.logger.warning(
            "Notifications unavailable (run migration 004): %s",
            error
        )

        return None


# -------------------------------------------------------------------
# AI assessment (runs ONLY after both parent OTPs are verified)
# -------------------------------------------------------------------

def run_ai_assessment(cursor, request_id, user_id):
    """
    Score the request using the security context captured at submission.

    The AI model is advisory only. The mentor still makes the decision.
    """

    cursor.execute(
        """
        SELECT
            known_device,
            location_deviation,
            failed_login_count,
            recent_password_reset,
            mfa_verified,
            phone_change_frequency,
            login_time_deviation
        FROM security_context
        WHERE request_id = %s
        """,
        (request_id,)
    )

    row = cursor.fetchone()

    if not row:
        raise RuntimeError(
            f"Security context missing for request {request_id}"
        )

    features = {
        "known_device": int(row["known_device"]),
        "location_deviation": float(row["location_deviation"]),
        "failed_login_count": int(row["failed_login_count"]),
        "recent_password_reset": int(row["recent_password_reset"]),
        "mfa_verified": int(row["mfa_verified"]),
        "phone_change_frequency": int(row["phone_change_frequency"]),
        "login_time_deviation": float(row["login_time_deviation"]),
    }

    started_at = time.perf_counter()

    risk_result = predict_risk(features)

    latency_ms = round(
        (time.perf_counter() - started_at) * 1000.0, 3
    )

    risk_score = max(
        0.0,
        min(100.0, float(risk_result["risk_score"]))
    )

    risk_level = determine_risk_level(risk_score)

    risk_factors = build_risk_factors(features)

    # The previous assessment, if any, decides whether this run is a
    # new/changed assessment or an unchanged retry.
    cursor.execute(
        """
        SELECT risk_score, risk_level
        FROM ai_assessments
        WHERE request_id = %s
        """,
        (request_id,)
    )

    previous = cursor.fetchone()

    changed = (
        previous is None
        or float(previous["risk_score"]) != risk_score
        or previous["risk_level"] != risk_level
    )

    cursor.execute(
        """
        INSERT INTO ai_assessments
        (
            request_id,
            risk_score,
            risk_level,
            risk_factors,
            model_version
        )
        VALUES
        (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            risk_score = VALUES(risk_score),
            risk_level = VALUES(risk_level),
            risk_factors = VALUES(risk_factors),
            model_version = VALUES(model_version),
            assessed_at = NOW()
        """,
        (
            request_id,
            risk_score,
            risk_level,
            json.dumps(risk_factors),
            MODEL_VERSION
        )
    )

    # ---- monitoring record -------------------------------------
    # The stored feature vector is exactly what the model scored, so the
    # explanation shown later is computed from the real inputs.
    try:
        model_registry.record_prediction(
            cursor,
            request_id=request_id,
            user_id=user_id,
            model_version=MODEL_VERSION,
            risk_score=risk_score,
            risk_level=risk_level,
            latency_ms=latency_ms,
            feature_values=features,
        )
    except mysql.connector.Error as error:
        if error.errno not in (1146, 1054):
            raise
        app.logger.warning(
            "Prediction monitoring unavailable (run migration 005): %s",
            error
        )

    # ---- anomaly indicators + alert ----------------------------
    indicator_result = anomaly.evaluate(features)
    alert_id = None

    if indicator_result["count"]:
        try:
            alert_id = anomaly.upsert_alert(
                cursor, request_id, user_id, indicator_result
            )
        except mysql.connector.Error as error:
            if error.errno not in (1146, 1054):
                raise
            app.logger.warning(
                "Security alerts unavailable (run migration 005): %s",
                error
            )

    write_audit(
        cursor,
        request_id,
        user_id,
        "System",
        "AI_ASSESSMENT_GENERATED" if changed else "AI_ASSESSMENT_RETRY_UNCHANGED",
        {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "model_version": MODEL_VERSION,
            "indicator_count": indicator_result["count"],
            "indicator_severity": indicator_result["severity"],
        }
    )

    # Only a new or changed assessment produces a timeline entry, so a
    # repeated retry cannot flood the request history.
    if changed:
        create_timeline_event(
            cursor,
            request_id,
            "AI_ASSESSED",
            timeline.CATEGORY_AI,
            f"AI risk assessed: {risk_level}",
            summary=f"Risk score {risk_score:.2f}",
            details={
                "risk_score": risk_score,
                "risk_level": risk_level,
                "model_version": MODEL_VERSION,
                "indicator_count": indicator_result["count"],
            },
        )

    mentor_id = None
    student_name = "The student"

    cursor.execute(
        """
        SELECT p.mentor_id, u.name
        FROM phone_change_requests p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.request_id = %s
        """,
        (request_id,)
    )

    owner = cursor.fetchone() or {}

    mentor_id = owner.get("mentor_id") or get_active_mentor(
        cursor, user_id
    )
    student_name = owner.get("name") or student_name

    if indicator_result["count"]:

        # An unchanged retry must not repeat the alert timeline entry or
        # the mentor's inbox notification.
        if changed:
            create_timeline_event(
                cursor,
                request_id,
                "ALERT_RAISED",
                timeline.CATEGORY_ALERT,
                "Anomaly indicators raised",
                summary=indicator_result["summary"],
                details={
                    "severity": indicator_result["severity"],
                    "score": indicator_result["score"],
                    "indicators": [
                        item["code"]
                        for item in indicator_result["indicators"]
                    ],
                },
            )

            if mentor_id:
                _notify_inbox_safely(
                    cursor,
                    mentor_id,
                    NOTIFY_SECURITY_ALERT,
                    request_id,
                    (
                        f"Security alert for {student_name} "
                        f"({request_id}): "
                        f"{indicator_result['summary']}"
                    )[:500]
                )

        # Critical evidence always freezes the request. This is a
        # backend rule; the UI cannot override it.
        if indicator_result["severity"] == anomaly.SEVERITY_CRITICAL:
            cursor.execute(
                """
                UPDATE phone_change_requests
                SET status = 'SECURITY_HOLD'
                WHERE request_id = %s
                  AND status = 'PENDING'
                """,
                (request_id,)
            )

            if cursor.rowcount:
                write_audit(
                    cursor,
                    request_id,
                    user_id,
                    "System",
                    "SECURITY_HOLD_RAISED",
                    {
                        "reason": "critical_anomaly_indicators",
                        "indicators": [
                            item["code"]
                            for item in indicator_result["indicators"]
                        ],
                    }
                )

                create_timeline_event(
                    cursor,
                    request_id,
                    "SECURITY_HOLD",
                    timeline.CATEGORY_ALERT,
                    "Request frozen by security hold",
                    summary="Critical anomaly indicators were present.",
                    details={
                        "severity": indicator_result["severity"],
                        "score": indicator_result["score"],
                    },
                )

                _notify_inbox_safely(
                    cursor,
                    user_id,
                    NOTIFY_SECURITY_HOLD,
                    request_id,
                    (
                        "Your phone-change request was paused for a "
                        "security review. Your mentor has been notified."
                    )
                )

                for admin_id in _active_admin_ids(cursor):
                    _notify_inbox_safely(
                        cursor,
                        admin_id,
                        NOTIFY_SECURITY_ALERT,
                        request_id,
                        (
                            f"Critical security alert for {student_name} "
                            f"({request_id})."
                        )
                    )

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "indicators": indicator_result,
        "alert_id": alert_id,
        "latency_ms": latency_ms,
    }


# -------------------------------------------------------------------
# AI assessment orchestration
#
# The AI assessment runs in its OWN transaction, after the parent
# verification transaction has committed. That separation is the whole
# point: a broken model must never be able to undo a successful parent
# verification.
#
# The assessment state machine lives in ai_assessment_status:
#
#     PENDING   the assessment is owed
#     COMPLETED the assessment is stored and the request is reviewable
#     FAILED    the assessment could not be produced; the request stays
#               blocked until a retry succeeds
#
# A request may only be APPROVED while its assessment is COMPLETED.
# -------------------------------------------------------------------

AI_STATUS_PENDING = "PENDING"
AI_STATUS_COMPLETED = "COMPLETED"
AI_STATUS_FAILED = "FAILED"


def _safe_error_text(error):
    """
    A short, loggable description of a failure.

    Only the exception type and a truncated message are kept. No OTP
    code, token, hash or password ever reaches this string.
    """

    try:
        message = str(error)
    except Exception:
        message = ""

    message = " ".join(message.split())

    if not message:
        return type(error).__name__

    return f"{type(error).__name__}: {message}"[:450]


def _migration_006_missing(error):
    """
    True when the error means migration 006 has not been applied.

    The AI assessment state table is bookkeeping. A deployment that has
    not run the migration yet keeps working: the assessment still runs
    and is still stored, it is only the retry bookkeeping that is
    missing.
    """

    return getattr(error, "errno", None) in (1146, 1054)


def mark_ai_assessment_owed(cursor, request_id):
    """
    Record that this request owes an AI assessment.

    Called inside the parent verification transaction, so a request can
    never be marked VERIFIED without also recording that an assessment
    is owed.
    """

    try:
        cursor.execute(
            """
            INSERT INTO ai_assessment_status
            (
                request_id,
                status,
                attempts,
                last_attempt_at
            )
            VALUES
            (%s, %s, 0, NULL)
            ON DUPLICATE KEY UPDATE
                status = %s,
                completed_at = NULL,
                updated_at = NOW()
            """,
            (request_id, AI_STATUS_PENDING, AI_STATUS_PENDING)
        )
    except mysql.connector.Error as error:
        if not _migration_006_missing(error):
            raise

        app.logger.warning(
            "AI assessment state unavailable (run migration 006): %s",
            error
        )


def load_ai_assessment_state(cursor, request_id):
    """
    The assessment state of a request, or None when it has no row.

    A request created before this change (no state row) but with a
    stored assessment is treated as COMPLETED: the assessment exists,
    which is what the approval gate needs to know.
    """

    state = None

    try:
        cursor.execute(
            """
            SELECT
                request_id,
                status,
                attempts,
                last_error,
                last_attempt_at,
                completed_at
            FROM ai_assessment_status
            WHERE request_id = %s
            """,
            (request_id,)
        )

        state = cursor.fetchone()

    except mysql.connector.Error as error:
        if not _migration_006_missing(error):
            raise

        app.logger.warning(
            "AI assessment state unavailable (run migration 006): %s",
            error
        )

    if state:
        return state

    # No state row: a stored assessment means the request was assessed
    # (for example before this change existed).
    cursor.execute(
        """
        SELECT assessment_id
        FROM ai_assessments
        WHERE request_id = %s
        LIMIT 1
        """,
        (request_id,)
    )

    if cursor.fetchone():
        return {
            "request_id": request_id,
            "status": AI_STATUS_COMPLETED,
            "attempts": 1,
            "last_error": None,
            "last_attempt_at": None,
            "completed_at": None,
        }

    return None


def ai_assessment_blocks_approval(cursor, request_id):
    """
    True when the request must not be approved yet.

    The request is blocked while its required AI assessment is missing
    or failed. A stored assessment that is COMPLETED (or a legacy
    request that already carries an assessment) does not block.
    """

    state = load_ai_assessment_state(cursor, request_id)

    return state is None or state["status"] != AI_STATUS_COMPLETED


def execute_ai_assessment(request_id, user_id, trigger="dual_otp"):
    """
    Run the AI assessment for a request in its own transaction.

    Never raises. A failure is recorded (state FAILED, audit entry,
    mentor notification) and reported in the return value, so the
    caller - and above all the committed parent verification - is never
    affected by a broken model.
    """

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        # ---- 1. record the attempt (committed on its own) --------
        connection.start_transaction()

        try:
            cursor.execute(
                """
                INSERT INTO ai_assessment_status
                (
                    request_id,
                    status,
                    attempts,
                    last_attempt_at
                )
                VALUES
                (%s, %s, 1, NOW())
                ON DUPLICATE KEY UPDATE
                    status = %s,
                    attempts = attempts + 1,
                    last_attempt_at = NOW(),
                    updated_at = NOW()
                """,
                (request_id, AI_STATUS_PENDING, AI_STATUS_PENDING)
            )
        except mysql.connector.Error as error:
            if not _migration_006_missing(error):
                raise

            app.logger.warning(
                "AI assessment state unavailable (run migration 006): %s",
                error
            )

        connection.commit()

        # ---- 2. run the assessment (its own transaction) ---------
        connection.start_transaction()

        result = run_ai_assessment(cursor, request_id, user_id)

        try:
            cursor.execute(
                """
                UPDATE ai_assessment_status
                SET
                    status = %s,
                    completed_at = NOW(),
                    last_error = NULL,
                    updated_at = NOW()
                WHERE request_id = %s
                """,
                (AI_STATUS_COMPLETED, request_id)
            )
        except mysql.connector.Error as error:
            if not _migration_006_missing(error):
                raise

            app.logger.warning(
                "AI assessment state unavailable (run migration 006): %s",
                error
            )

        connection.commit()

        app.logger.info(
            "AI assessment completed for request %s (%s)",
            request_id,
            trigger
        )

        return {
            "success": True,
            "status": AI_STATUS_COMPLETED,
            "result": result,
        }

    except Exception as error:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        app.logger.exception(
            "AI assessment failed for request %s (%s)",
            request_id,
            trigger
        )

        _record_ai_assessment_failure(
            request_id,
            user_id,
            error,
            trigger
        )

        return {
            "success": False,
            "status": AI_STATUS_FAILED,
            "error": _safe_error_text(error),
        }

    finally:
        close_db(cursor, connection)


def _record_ai_assessment_failure(request_id, user_id, error, trigger):
    """
    Record an AI assessment failure without touching anything else.

    The parent verification, the OTPs and the request state are left
    exactly as they are: only the assessment state, the audit trail and
    the mentor's inbox describe the failure.
    """

    error_text = _safe_error_text(error)

    connection = None
    cursor = None

    mentor_email = None
    student_name = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()

        try:
            cursor.execute(
                """
                INSERT INTO ai_assessment_status
                (
                    request_id,
                    status,
                    attempts,
                    last_error,
                    last_attempt_at
                )
                VALUES
                (%s, %s, 1, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    status = %s,
                    last_error = %s,
                    last_attempt_at = NOW(),
                    updated_at = NOW()
                """,
                (
                    request_id,
                    AI_STATUS_FAILED,
                    error_text,
                    AI_STATUS_FAILED,
                    error_text,
                )
            )
        except mysql.connector.Error as error:
            if not _migration_006_missing(error):
                raise

            app.logger.warning(
                "AI assessment state unavailable (run migration 006): %s",
                error
            )

        write_audit(
            cursor,
            request_id,
            user_id,
            "System",
            "AI_ASSESSMENT_FAILED",
            {
                "trigger": trigger,
                "error": error_text,
                "retryable": True,
            }
        )

        create_timeline_event(
            cursor,
            request_id,
            "AI_ASSESSMENT_FAILED",
            timeline.CATEGORY_AI,
            "AI assessment could not be produced",
            summary=(
                "The risk assessment is temporarily unavailable. "
                "The request stays blocked until it is retried."
            ),
            details={
                "trigger": trigger,
                "error": error_text,
            },
        )

        cursor.execute(
            """
            SELECT
                p.mentor_id,
                u.name AS student_name,
                m.email AS mentor_email
            FROM phone_change_requests p
            JOIN users u
                ON u.user_id = p.user_id
            LEFT JOIN users m
                ON m.user_id = p.mentor_id
            WHERE p.request_id = %s
            """,
            (request_id,)
        )

        owner = cursor.fetchone() or {}

        mentor_id = owner.get("mentor_id") or get_active_mentor(
            cursor, user_id
        )

        student_name = owner.get("student_name") or "The student"
        mentor_email = owner.get("mentor_email")

        if mentor_id:
            _notify_inbox_safely(
                cursor,
                mentor_id,
                NOTIFY_AI_UNAVAILABLE,
                request_id,
                inapp_ai_unavailable(
                    student_name, request_id
                )
            )

        connection.commit()

    except Exception:
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass

        app.logger.exception(
            "Could not record the AI assessment failure for request %s",
            request_id
        )

    finally:
        close_db(cursor, connection)

    # The mentor is told outside the transaction: a slow mail server
    # must never hold a database lock.
    if mentor_email:
        _notify_safely(
            "Mentor AI-unavailable notice",
            send_email,
            mentor_email,
            f"EduShield AI — AI assessment unavailable {request_id}",
            email_mentor_ai_unavailable(
                student_name or "The student",
                request_id
            )
        )


def _active_admin_ids(cursor):
    """Active admin user_ids, for fan-out notifications."""

    cursor.execute(
        """
        SELECT user_id
        FROM users
        WHERE role = 'admin'
          AND account_status = 'active'
        """
    )

    return [row["user_id"] for row in cursor.fetchall()]


# -------------------------------------------------------------------
# Create phone-change request
# -------------------------------------------------------------------

@app.route(
    "/api/phone-change-requests",
    methods=["POST"]
)
@require_auth(
    allowed_roles=["student"]
)
def create_phone_change_request():

    data = request.get_json(
        silent=True
    ) or {}

    new_phone = str(
        data.get("new_phone", "")
    ).strip()

    if not new_phone:
        return jsonify({
            "success": False,
            "message": "new_phone is required"
        }), 400

    if not re.fullmatch(r"\d{10}", new_phone):
        return jsonify({
            "success": False,
            "message": "Phone number must contain exactly 10 digits"
        }), 400

    user_id = request.user["user_id"]

    device_id = get_client_device_id()

    latitude, longitude = get_client_location()

    # Limit how often one student can open phone-change requests.
    limited = rate_limit_exceeded(
        "request-create",
        user_id,
        5,
        3600,
        "Too many phone-change requests. Please try again later."
    )

    if limited:
        return limited

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        # Serialise submissions for this student. Without this lock two
        # concurrent requests can both pass the open-request check and
        # create duplicate pending requests.
        cursor.execute(
            """
            SELECT
                name,
                email,
                parent_email,
                parent_phone,
                phone_number,
                mentor_id,
                account_status
            FROM users
            WHERE user_id = %s
            FOR UPDATE
            """,
            (user_id,)
        )

        user_row = cursor.fetchone()

        if not user_row:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "User not found"
            }), 404

        if user_row.get("account_status") != "active":
            connection.rollback()
            return jsonify({
                "success": False,
                "message":
                    "Activate your account before requesting a change"
            }), 403

        if not user_row["parent_email"] or not user_row["parent_phone"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message":
                    "Parent SMS and email must both be registered "
                    "before a phone change can be requested"
            }), 400

        if not normalize_phone_e164(user_row["parent_phone"]):
            connection.rollback()
            return jsonify({
                "success": False,
                "message":
                    "The registered parent phone number is not valid. "
                    "Contact the school to correct it."
            }), 400

        old_phone = user_row["phone_number"]

        if old_phone == new_phone:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "New phone number must be different "
                    "from the current phone number"
                )
            }), 400

        # One open request per student keeps the flow simple to audit.
        # A SECURITY_HOLD request is still open: allowing a second
        # request would let a student route around an unresolved hold.
        cursor.execute(
            """
            SELECT request_id
            FROM phone_change_requests
            WHERE user_id = %s
              AND status IN ('PENDING', 'SECURITY_HOLD')
            LIMIT 1
            """,
            (user_id,)
        )

        if cursor.fetchone():
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "You already have an open phone-change request. "
                    "Wait for it to finish or cancel it first."
                )
            }), 409

        # The mentor comes from the assignment table, not users.mentor_id.
        mentor_id = get_active_mentor(cursor, user_id)

        request_id = (
            "REQ"
            + uuid.uuid4().hex[:12].upper()
        )

        # Security context is captured now, but the AI assessment is
        # deferred until both parent OTPs are verified.
        security_features = collect_security_features(
            connection,
            user_id,
            device_id=device_id,
            latitude=latitude,
            longitude=longitude
        )

        trust_score = security_features["trust_score"]

        # Parent link token (only its hash is stored).
        parent_link_token = generate_link_token()
        parent_token_hash = hash_link_token(parent_link_token)

        # Two INDEPENDENT codes.
        sms_code = generate_otp()
        email_code = generate_otp()

        cursor.execute(
            """
            INSERT INTO phone_change_requests
            (
                request_id,
                user_id,
                old_phone,
                new_phone,
                auth_status,
                parent_verification_status,
                status,
                mentor_id,
                parent_token_hash,
                parent_token_expires_at
            )
            VALUES
            (
                %s, %s, %s, %s, 'PENDING', 'PENDING', 'PENDING', %s, %s,
                DATE_ADD(NOW(), INTERVAL %s MINUTE)
            )
            """,
            (
                request_id,
                user_id,
                old_phone,
                new_phone,
                mentor_id,
                parent_token_hash,
                PARENT_LINK_TTL_MINUTES
            )
        )

        cursor.execute(
            """
            INSERT INTO security_context
            (
                request_id,
                known_device,
                location_deviation,
                failed_login_count,
                recent_password_reset,
                mfa_verified,
                phone_change_frequency,
                login_time_deviation,
                trust_score
            )
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request_id,
                security_features["known_device"],
                security_features["location_deviation"],
                security_features["failed_login_count"],
                security_features["recent_password_reset"],
                security_features["mfa_verified"],
                security_features["phone_change_frequency"],
                security_features["login_time_deviation"],
                trust_score
            )
        )

        for channel, code in (("SMS", sms_code), ("EMAIL", email_code)):
            cursor.execute(
                """
                INSERT INTO phone_change_otps
                (
                    request_id,
                    channel,
                    code_hash,
                    expires_at
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    DATE_ADD(NOW(), INTERVAL %s MINUTE)
                )
                """,
                (
                    request_id,
                    channel,
                    hash_otp(request_id, channel, code),
                    OTP_TTL_MINUTES
                )
            )

        write_audit(
            cursor,
            request_id,
            user_id,
            "Student",
            "PHONE_CHANGE_REQUESTED",
            {"old_phone_masked": mask_phone(old_phone),
             "new_phone_masked": mask_phone(new_phone)}
        )

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print("Create phone change error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to create phone change request"
        }), 500

    finally:
        close_db(cursor, connection)

    # ---------------------------------------------------------------
    # Deliver notifications AFTER the commit.
    # Codes are sent once and are never returned in the API response.
    # ---------------------------------------------------------------

    parent_phone_e164 = normalize_phone_e164(user_row["parent_phone"])
    student_name = user_row["name"]
    parent_email = user_row["parent_email"]

    verify_url = (
        f"{_base_url()}/parent/verify/{parent_link_token}"
    )

    delivery = {"sms": False, "email": False}

    try:
        if not parent_phone_e164:
            raise DeliveryError("Parent phone number is not valid.")

        send_sms(parent_phone_e164, sms_parent_code_text(sms_code), request_id=request_id)
        delivery["sms"] = True

    except DeliveryError as e:
        print(f"Parent SMS not delivered: {e}", flush=True)

    try:
        send_email(
            parent_email,
            "EduShield AI - Verification Required",
            email_parent_verification_body(
                student_name,
                mask_phone(new_phone),
                verify_url,
                email_code
            ),
            html=email_parent_verification_html(
                student_name,
                mask_phone(new_phone),
                verify_url,
                email_code
            )
        )
        delivery["email"] = True

    except DeliveryError as e:
        print(f"⚠️ Parent email not delivered: {e}", flush=True)

    # Delivery results are written to the audit trail.
    audit_conn = get_db()
    audit_cursor = audit_conn.cursor()

    try:
        write_audit(
            audit_cursor,
            request_id,
            user_id,
            "System",
            "SMS_OTP_SENT" if delivery["sms"] else "SMS_OTP_SEND_FAILED"
        )
        write_audit(
            audit_cursor,
            request_id,
            user_id,
            "System",
            "EMAIL_OTP_SENT" if delivery["email"] else "EMAIL_OTP_SEND_FAILED"
        )
        audit_conn.commit()
    finally:
        close_db(audit_cursor, audit_conn)

    if mentor_id:
        mentor_email = _get_user_email(mentor_id)

        _notify_safely(
            "Mentor request notice",
            send_email,
            mentor_email,
            f"EduShield AI — New phone-change request {request_id}",
            email_mentor_new_request(student_name, request_id)
        )

    return jsonify({
        "success": True,
        "message": (
            "Phone change request submitted. "
            "The parent has been asked to verify by SMS and email."
        ),
        "request_id": request_id,
        "status": "PENDING",
        "auth_status": "PENDING",
        "parent_delivery": delivery,
        "ai_assessment": None,
        "note": (
            "AI risk assessment runs after the parent completes "
            "both verifications."
        )
    }), 201


def _base_url():
    return os.getenv(
        "EDUSHIELD_BASE_URL",
        "http://127.0.0.1:5000"
    ).rstrip("/")


def _get_user_email(user_id):
    connection = get_db()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT email FROM users WHERE user_id = %s",
            (user_id,)
        )
        row = cursor.fetchone()
        return row["email"] if row else None

    finally:
        close_db(cursor, connection)


def _get_user_name(cursor, user_id):
    """Return a user's display name using the caller's cursor/transaction."""

    cursor.execute(
        "SELECT name FROM users WHERE user_id = %s",
        (user_id,)
    )

    row = cursor.fetchone()

    return row["name"] if row else "The student"


# -------------------------------------------------------------------
# Student cancellation (soft: the record is kept for the audit trail)
# -------------------------------------------------------------------

@app.route(
    "/api/phone-change-requests/<request_id>/cancel",
    methods=["POST"]
)
@require_auth(
    allowed_roles=["student"]
)
def cancel_phone_change_request(request_id):

    user_id = request.user["user_id"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT user_id, status, mentor_id
            FROM phone_change_requests
            WHERE request_id = %s
            FOR UPDATE
            """,
            (request_id,)
        )

        req = cursor.fetchone()

        if not req:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        if req["user_id"] != user_id:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Not your request"
            }), 403

        if req["status"] != "PENDING":
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Request is already {req['status']}"
            }), 400

        cursor.execute(
            """
            UPDATE phone_change_requests
            SET
                status = 'CANCELLED',
                parent_token_expires_at = NOW()
            WHERE request_id = %s
            """,
            (request_id,)
        )

        # Lock any unused codes so they cannot be entered later.
        cursor.execute(
            """
            UPDATE phone_change_otps
            SET locked = 1, code_hash = NULL
            WHERE request_id = %s AND verified = 0
            """,
            (request_id,)
        )

        write_audit(
            cursor,
            request_id,
            user_id,
            "Student",
            "PHONE_CHANGE_CANCELLED"
        )

        # If the student had already asked the mentor to look at this
        # request, tell the mentor it is gone so they do not chase it.
        if req["mentor_id"]:
            cursor.execute(
                """
                SELECT 1
                FROM notifications
                WHERE request_id = %s
                  AND user_id = %s
                  AND type = %s
                LIMIT 1
                """,
                (request_id, req["mentor_id"], NOTIFY_MENTOR_NOTIFIED)
            )

            if cursor.fetchone():
                student_name = _get_user_name(cursor, user_id)

                create_notification(
                    cursor,
                    req["mentor_id"],
                    NOTIFY_REQUEST_CANCELLED,
                    request_id,
                    inapp_request_cancelled(student_name, request_id)
                )

        connection.commit()

        return jsonify({
            "success": True,
            "message": "Request cancelled",
            "request_id": request_id,
            "status": "CANCELLED"
        })

    except Exception as e:
        if connection:
            connection.rollback()

        print("Cancel request error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to cancel request"
        }), 500

    finally:
        close_db(cursor, connection)


# -------------------------------------------------------------------
# Student soft delete (the record is kept for the audit trail)
#
# A student may hide a request from their own list. The row is never
# removed; mentors and admins still see it. Only PENDING or CANCELLED
# requests can be hidden; anything else is a 409 conflict.
# -------------------------------------------------------------------

@app.route(
    "/api/phone-change-requests/<request_id>/delete",
    methods=["POST"]
)
@require_auth(
    allowed_roles=["student"]
)
def delete_phone_change_request(request_id):

    user_id = request.user["user_id"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT user_id, status, deleted_by_student
            FROM phone_change_requests
            WHERE request_id = %s
            FOR UPDATE
            """,
            (request_id,)
        )

        req = cursor.fetchone()

        if not req:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        if req["user_id"] != user_id:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        if req["status"] not in ("PENDING", "CANCELLED"):
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    f"Request is {req['status']} and can no longer "
                    "be removed from your list"
                ),
                "status": req["status"]
            }), 409

        cursor.execute(
            """
            UPDATE phone_change_requests
            SET deleted_by_student = 1
            WHERE request_id = %s
            """,
            (request_id,)
        )

        write_audit(
            cursor,
            request_id,
            user_id,
            "Student",
            "REQUEST_DELETED_BY_STUDENT",
            {"previous_status": req["status"]}
        )

        connection.commit()

        return jsonify({
            "success": True,
            "message": "Request removed from your list",
            "request_id": request_id,
            "status": req["status"]
        })

    except Exception as e:
        if connection:
            connection.rollback()

        print("Student delete error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to remove request"
        }), 500

    finally:
        close_db(cursor, connection)


# -------------------------------------------------------------------
# Student: notify mentor
#
# Asks the assigned mentor to look at a pending request. Limited to one
# nudge per request per six hours, and three per request in total, so it
# cannot be used to spam the mentor. Creates an in-app notification and
# an email. The email contains only names, the request id and a link.
# -------------------------------------------------------------------

NOTIFY_MENTOR_COOLDOWN_SECONDS = 6 * 60 * 60
NOTIFY_MENTOR_MAX_PER_REQUEST = 3


@app.route(
    "/api/phone-change-requests/<request_id>/notify-mentor",
    methods=["POST"]
)
@require_auth(
    allowed_roles=["student"]
)
def notify_mentor(request_id):

    user_id = request.user["user_id"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                user_id, status, mentor_id, deleted_by_student,
                requested_at
            FROM phone_change_requests
            WHERE request_id = %s
            FOR UPDATE
            """,
            (request_id,)
        )

        req = cursor.fetchone()

        # A request the caller does not own is reported as not found so
        # the API never confirms another student's request exists.
        if not req or req["user_id"] != user_id:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        if req["status"] != "PENDING":
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "Only pending requests can notify the mentor"
                ),
                "status": req["status"]
            }), 409

        mentor_id = get_active_mentor(cursor, user_id)

        if not mentor_id:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "You do not have an active mentor to notify"
                )
            }), 409

        # Enforce the per-request ceiling first, then the cooldown.
        cursor.execute(
            """
            SELECT COUNT(*) AS sent
            FROM notifications
            WHERE request_id = %s
              AND user_id = %s
              AND type = %s
            """,
            (request_id, mentor_id, NOTIFY_MENTOR_NOTIFIED)
        )

        sent = cursor.fetchone()["sent"]

        if sent >= NOTIFY_MENTOR_MAX_PER_REQUEST:
            connection.rollback()
            response = jsonify({
                "success": False,
                "message": (
                    "You have already notified your mentor the maximum "
                    "number of times for this request"
                )
            })
            response.status_code = 429
            return response

        cursor.execute(
            """
            SELECT created_at
            FROM notifications
            WHERE request_id = %s
              AND user_id = %s
              AND type = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (request_id, mentor_id, NOTIFY_MENTOR_NOTIFIED)
        )

        last = cursor.fetchone()

        if last and last["created_at"]:
            cursor.execute(
                """
                SELECT TIMESTAMPDIFF(
                    SECOND, %s, NOW()
                ) AS age
                """,
                (last["created_at"],)
            )

            age = cursor.fetchone()["age"] or 0

            if age < NOTIFY_MENTOR_COOLDOWN_SECONDS:
                connection.rollback()
                retry_after = NOTIFY_MENTOR_COOLDOWN_SECONDS - age
                response = jsonify({
                    "success": False,
                    "message": (
                        "Your mentor was notified recently. Please wait "
                        "before notifying again."
                    ),
                    "retry_after_seconds": retry_after
                })
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response

        student_name = _get_user_name(cursor, user_id)

        create_notification(
            cursor,
            mentor_id,
            NOTIFY_MENTOR_NOTIFIED,
            request_id,
            inapp_mentor_notified(student_name, request_id)
        )

        write_audit(
            cursor,
            request_id,
            user_id,
            "Student",
            "MENTOR_NOTIFIED",
            {"mentor_id": mentor_id}
        )

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print("Notify mentor error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to notify mentor"
        }), 500

    finally:
        close_db(cursor, connection)

    mentor_email = _get_user_email(mentor_id)

    _notify_safely(
        "Mentor nudge",
        send_email,
        mentor_email,
        f"EduShield AI — Review requested {request_id}",
        email_notify_mentor_request(
            student_name,
            request_id,
            f"{_base_url()}/mentor-dashboard"
        )
    )

    return jsonify({
        "success": True,
        "message": "Your mentor has been notified",
        "request_id": request_id
    })


# -------------------------------------------------------------------
# Notifications inbox
#
# Every user sees only their own rows. Reading is scoped by user_id, so
# a user can never read or mark another user's notification. Marking an
# unknown or foreign notification as read returns 404 (never 403), which
# avoids confirming that the id exists.
# -------------------------------------------------------------------

@app.route(
    "/api/notifications",
    methods=["GET"]
)
@require_auth()
def list_notifications():

    user_id = request.user["user_id"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                notification_id,
                type,
                request_id,
                message,
                created_at,
                read_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC, notification_id DESC
            """,
            (user_id,)
        )

        items = cursor.fetchall()

        for item in items:
            serialize_record(item)
            item["read"] = item.get("read_at") is not None

        unread = sum(1 for item in items if not item["read"])

        return jsonify({
            "success": True,
            "count": len(items),
            "unread": unread,
            "notifications": items
        })

    except Exception:
        app.logger.exception("Failed to fetch notifications")

        return jsonify({
            "success": False,
            "message": "Failed to fetch notifications"
        }), 500

    finally:
        close_db(cursor, connection)


@app.route(
    "/api/notifications/<int:notification_id>/read",
    methods=["POST"]
)
@require_auth()
def mark_notification_read(notification_id):

    user_id = request.user["user_id"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT user_id, read_at
            FROM notifications
            WHERE notification_id = %s
            FOR UPDATE
            """,
            (notification_id,)
        )

        row = cursor.fetchone()

        if not row or row["user_id"] != user_id:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Notification not found"
            }), 404

        if row["read_at"] is None:
            cursor.execute(
                """
                UPDATE notifications
                SET read_at = NOW()
                WHERE notification_id = %s
                """,
                (notification_id,)
            )

        connection.commit()

        return jsonify({
            "success": True,
            "notification_id": notification_id
        })

    except Exception as e:
        if connection:
            connection.rollback()

        print("Mark notification read error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to mark notification as read"
        }), 500

    finally:
        close_db(cursor, connection)


# -------------------------------------------------------------------
# List phone-change requests
# -------------------------------------------------------------------

@app.route(
    "/api/phone-change-requests",
    methods=["GET"]
)
@require_auth()
def list_phone_change_requests():

    user_id = request.user[
        "user_id"
    ]

    role = request.user[
        "role"
    ]

    connection = None
    cursor = None

    try:

        connection = get_db()

        cursor = connection.cursor(
            dictionary=True
        )

        base_query = """
            SELECT
                p.request_id,
                p.user_id,
                p.old_phone,
                p.new_phone,
                p.requested_at,

                p.auth_status,

                p.parent_verification_status,
                p.parent_verified_at,

                p.status,
                p.mentor_id,
                p.reviewed_at,
                p.rejection_reason,

                a.risk_score,
                a.risk_level,
                a.risk_factors,
                a.model_version,
                a.assessed_at

            FROM phone_change_requests p

            LEFT JOIN ai_assessments a
                ON p.request_id = a.request_id
        """

        # -----------------------------------------------------------
        # Student
        # -----------------------------------------------------------

        if role == "student":

            cursor.execute(
                base_query
                + """
                WHERE p.user_id = %s
                  AND p.deleted_by_student = 0

                ORDER BY
                    p.requested_at DESC
                """,
                (user_id,)
            )

        # -----------------------------------------------------------
        # Mentor
        # -----------------------------------------------------------

        elif role == "mentor":

            cursor.execute(
                base_query
                + """
                WHERE p.user_id IN (
                    SELECT student_id
                    FROM mentor_assignments
                    WHERE mentor_id = %s
                      AND active = 1
                )

                ORDER BY
                    p.requested_at DESC
                """,
                (user_id,)
            )

        # Admins have oversight of every request, including requests a
        # student has hidden from their own list.
        elif role == "admin":

            cursor.execute(
                base_query
                + """
                ORDER BY
                    p.requested_at DESC
                """
            )

        else:

            return jsonify({
                "success": False,
                "message":
                    "Unknown role"
            }), 403

        requests_list = (
            cursor.fetchall()
        )

        for item in requests_list:

            serialize_record(item)

            if isinstance(
                item.get(
                    "risk_factors"
                ),
                str
            ):

                try:

                    item[
                        "risk_factors"
                    ] = json.loads(
                        item[
                            "risk_factors"
                        ]
                    )

                except json.JSONDecodeError:

                    item[
                        "risk_factors"
                    ] = []

        return jsonify({

            "success": True,

            "count":
                len(requests_list),

            "requests":
                requests_list
        })

    except Exception:
        app.logger.exception("Failed to fetch phone change requests")

        return jsonify({
            "success": False,
            "message":
                "Failed to fetch phone change requests"
        }), 500

    finally:

        close_db(
            cursor,
            connection
        )


# -------------------------------------------------------------------
# Mentor review
# -------------------------------------------------------------------

@app.route(
    "/api/phone-change-requests/<request_id>",
    methods=["PATCH"]
)
@require_auth(
    allowed_roles=["mentor"]
)
def review_phone_change_request(
    request_id
):

    data = request.get_json(
        silent=True
    ) or {}

    decision = data.get("decision")
    reason = data.get("reason")

    if decision not in (
        "APPROVED",
        "REJECTED"
    ):
        return jsonify({
            "success": False,
            "message": (
                "decision must be "
                "'APPROVED' or 'REJECTED'"
            )
        }), 400

    mentor_id = request.user["user_id"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT *
            FROM phone_change_requests
            WHERE request_id = %s
            FOR UPDATE
            """,
            (request_id,)
        )

        req = cursor.fetchone()

        if not req:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        # Authorisation is by assignment. A request the mentor does not
        # manage is reported as not found (404), never 403, so the API
        # does not reveal that the request exists.
        if not mentor_manages_student(cursor, mentor_id, req["user_id"]):
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        # A request on SECURITY_HOLD stays reviewable, but only for
        # rejection. Every other non-pending state is final.
        if req["status"] not in ("PENDING", "SECURITY_HOLD"):
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Request already {req['status']}"
            }), 400

        # -----------------------------------------------------------
        # SERVER-SIDE GATES (the frontend is never trusted)
        # -----------------------------------------------------------

        if decision == "APPROVED":

            if req["status"] == "SECURITY_HOLD":
                connection.rollback()
                return jsonify({
                    "success": False,
                    "message": (
                        "Request is on security hold. "
                        "It can only be rejected."
                    )
                }), 403

            if req["auth_status"] != "VERIFIED":
                connection.rollback()
                return jsonify({
                    "success": False,
                    "message": (
                        "Parent SMS and email verification must both "
                        "be completed before approval"
                    ),
                    "auth_status": req["auth_status"]
                }), 403

            # The AI assessment is required. A request whose assessment
            # is missing or failed must never be approved: the mentor
            # would be deciding without the risk evidence.
            ai_state = load_ai_assessment_state(cursor, request_id)

            if ai_state is None or ai_state["status"] != AI_STATUS_COMPLETED:
                connection.rollback()
                return jsonify({
                    "success": False,
                    "message": (
                        "The risk assessment for this request is not "
                        "available yet. It must complete successfully "
                        "before the request can be approved."
                    ),
                    "ai_assessment_status": (
                        ai_state["status"] if ai_state else "MISSING"
                    )
                }), 403

        # -----------------------------------------------------------
        # Record the decision
        # -----------------------------------------------------------

        cursor.execute(
            """
            UPDATE phone_change_requests
            SET
                status = %s,
                reviewed_at = NOW(),
                rejection_reason = %s
            WHERE request_id = %s
            """,
            (
                decision,
                reason if decision == "REJECTED" else None,
                request_id
            )
        )

        cursor.execute(
            """
            INSERT INTO mentor_reviews
            (
                request_id,
                mentor_id,
                decision,
                reason
            )
            VALUES
            (%s, %s, %s, %s)
            """,
            (
                request_id,
                mentor_id,
                decision,
                reason
            )
        )

        if decision == "APPROVED":

            cursor.execute(
                """
                UPDATE users
                SET phone_number = %s
                WHERE user_id = %s
                """,
                (
                    req["new_phone"],
                    req["user_id"]
                )
            )

        write_audit(
            cursor,
            request_id,
            req["user_id"],
            "Mentor",
            f"MENTOR_{decision}",
            {
                "mentor_id": mentor_id,
                "reason": reason
            }
        )

        if decision == "APPROVED":
            write_audit(
                cursor,
                request_id,
                req["user_id"],
                "System",
                "PHONE_NUMBER_UPDATED",
                {"new_phone_masked": mask_phone(req["new_phone"])}
            )

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print("Mentor review error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to review request"
        }), 500

    finally:
        close_db(cursor, connection)

    # Notify the student and parent after the commit.
    _notify_decision(req, decision, reason)

    return jsonify({
        "success": True,
        "message": f"Request {decision.lower()}",
        "request_id": request_id,
        "status": decision
    })


def _notify_decision(req, decision, reason):
    contacts = _load_contacts(req["user_id"])

    if not contacts:
        return

    subject = (
        "EduShield AI — Phone-number change approved"
        if decision == "APPROVED"
        else "EduShield AI — Phone-number change rejected"
    )

    body = email_decision(
        contacts["student_name"],
        req["request_id"],
        decision,
        reason if decision == "REJECTED" else None
    )

    _notify_safely(
        "Student decision notice",
        send_email,
        contacts["student_email"],
        subject,
        body
    )

    _notify_safely(
        "Parent decision notice",
        send_email,
        contacts["parent_email"],
        subject,
        body
    )


def _load_contacts(user_id):
    connection = get_db()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                name AS student_name,
                email AS student_email,
                parent_email
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        return cursor.fetchone()

    finally:
        close_db(cursor, connection)


# -------------------------------------------------------------------
# Request detail
# -------------------------------------------------------------------

@app.route(
    "/api/phone-change-requests/<request_id>",
    methods=["GET"]
)
@require_auth()
def get_phone_change_request_detail(
    request_id
):

    user_id = request.user["user_id"]
    role = request.user["role"]

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                request_id,
                user_id,
                old_phone,
                new_phone,
                requested_at,
                auth_status,
                parent_verification_status,
                parent_verified_at,
                status,
                mentor_id,
                reviewed_at,
                rejection_reason
            FROM phone_change_requests
            WHERE request_id = %s
            """,
            (request_id,)
        )

        req = cursor.fetchone()

        if not req:
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        if role == "student" and req["user_id"] != user_id:
            return jsonify({
                "success": False,
                "message": "Not your request"
            }), 403

        if role == "mentor" and not mentor_manages_student(
            cursor, user_id, req["user_id"]
        ):
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        cursor.execute(
            """
            SELECT
                known_device,
                location_deviation,
                failed_login_count,
                recent_password_reset,
                mfa_verified,
                phone_change_frequency,
                login_time_deviation,
                trust_score,
                captured_at
            FROM security_context
            WHERE request_id = %s
            """,
            (request_id,)
        )

        security_context = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                risk_score,
                risk_level,
                risk_factors,
                model_version,
                assessed_at
            FROM ai_assessments
            WHERE request_id = %s
            """,
            (request_id,)
        )

        ai_assessment = cursor.fetchone()

        # The assessment state explains why a request may still be
        # blocked (assessment owed, running or failed).
        ai_state = load_ai_assessment_state(cursor, request_id)

        # Per-channel OTP state. Hashes are never returned.
        cursor.execute(
            """
            SELECT
                channel,
                verified,
                locked,
                attempts,
                (expires_at > NOW()) AS is_valid
            FROM phone_change_otps
            WHERE request_id = %s
            ORDER BY channel
            """,
            (request_id,)
        )

        otp_channels = [
            {
                "channel": row["channel"],
                "verified": bool(row["verified"]),
                "locked": bool(row["locked"]),
                "attempts": int(row["attempts"] or 0),
                "is_valid": bool(row["is_valid"])
            }
            for row in cursor.fetchall()
        ]

        serialize_record(req)
        serialize_record(security_context)
        serialize_record(ai_assessment)

        if (
            ai_assessment
            and isinstance(
                ai_assessment.get("risk_factors"),
                str
            )
        ):
            try:
                ai_assessment["risk_factors"] = json.loads(
                    ai_assessment["risk_factors"]
                )
            except json.JSONDecodeError:
                ai_assessment["risk_factors"] = []

        return jsonify({
            "success": True,
            "request": req,
            "security_context": security_context,
            "ai_assessment": ai_assessment,
            "ai_assessment_status": (
                ai_state["status"] if ai_state else "MISSING"
            ),
            "otp_channels": otp_channels
        })

    except Exception as e:
        print("Detail error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Failed to fetch request details"
        }), 500

    finally:
        close_db(cursor, connection)


# -------------------------------------------------------------------
# Parent verification (replaces the old single-click approval link)
#
# The parent is a verification authority only. The parent proves
# possession of the registered phone AND the registered email by
# entering two independent codes. The parent never approves or rejects.
# -------------------------------------------------------------------

def _load_parent_request(cursor, token, for_update=False):
    """Resolve a parent link token to its request. Only the hash is compared."""

    if not token:
        return None

    query = """
        SELECT
            p.request_id,
            p.user_id,
            p.old_phone,
            p.new_phone,
            p.status,
            p.auth_status,
            p.parent_verification_status,
            p.mentor_id,
            (p.parent_token_expires_at > NOW()) AS token_valid,
            u.name AS student_name,
            u.email AS student_email,
            u.parent_email,
            u.parent_phone,
            m.email AS mentor_email
        FROM phone_change_requests p
        JOIN users u
            ON p.user_id = u.user_id
        LEFT JOIN users m
            ON p.mentor_id = m.user_id
        WHERE p.parent_token_hash = %s
    """

    if for_update:
        query += " FOR UPDATE"

    cursor.execute(query, (hash_link_token(token),))

    return cursor.fetchone()


def _load_otp_states(cursor, request_id):
    cursor.execute(
        """
        SELECT
            channel,
            verified,
            locked,
            attempts,
            (expires_at > NOW()) AS is_valid
        FROM phone_change_otps
        WHERE request_id = %s
        ORDER BY FIELD(channel, 'SMS', 'EMAIL')
        """,
        (request_id,)
    )

    return [
        {
            "channel": row["channel"],
            "verified": bool(row["verified"]),
            "locked": bool(row["locked"]),
            "is_valid": bool(row["is_valid"]),
            "attempts_left": max(
                0,
                OTP_MAX_ATTEMPTS - int(row["attempts"] or 0)
            )
        }
        for row in cursor.fetchall()
    ]


def _verification_page_state(req):
    """Map the request into one display state for the parent page."""

    if req["status"] == "SECURITY_HOLD":
        return "held"

    if req["status"] != "PENDING":
        return "closed"

    if not req["token_valid"]:
        return "expired"

    return "open"


@app.route(
    "/parent/verify/<token>",
    methods=["GET"]
)
def parent_verify_page(token):

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        req = _load_parent_request(cursor, token)

        if not req:
            return render_template(
                "parent-verify.html",
                state="invalid"
            ), 404

        state = _verification_page_state(req)

        otps = _load_otp_states(cursor, req["request_id"])

        return render_template(
            "parent-verify.html",
            state=state,
            token=token,
            student_name=req["student_name"],
            new_phone_masked=mask_phone(req["new_phone"]),
            parent_email_masked=mask_email(req["parent_email"]),
            request_id=req["request_id"],
            status=req["status"],
            auth_status=req["auth_status"],
            otps=otps
        )

    except Exception as e:
        print("Parent verify page error:", repr(e), flush=True)

        return render_template(
            "parent-verify.html",
            state="error"
        ), 500

    finally:
        close_db(cursor, connection)


@app.route(
    "/parent/verify/<token>/<channel>",
    methods=["POST"]
)
def parent_verify_code(token, channel):

    channel = str(channel).upper()

    if channel not in CHANNELS:
        return jsonify({
            "success": False,
            "message": "Unknown verification channel"
        }), 400

    data = request.get_json(
        silent=True
    ) or {}

    code = str(data.get("code", "")).strip()

    if not is_valid_otp_format(code):
        return jsonify({
            "success": False,
            "message": f"Enter the {OTP_LENGTH}-digit code"
        }), 400

    # Throttle guessing: per client IP and per verification link.
    limited = rate_limit_exceeded(
        "parent-verify-ip",
        get_client_ip(),
        30,
        60,
        "Too many verification attempts. Please try again later."
    )

    if limited:
        return limited

    limited = rate_limit_exceeded(
        "parent-verify-token",
        token,
        10,
        60,
        "Too many verification attempts for this link. Please try again later."
    )

    if limited:
        return limited

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        req = _load_parent_request(cursor, token, for_update=True)

        if not req:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "This verification link is invalid."
            }), 404

        # A closed request (held, cancelled, or completed) is reported as
        # closed, even if its link has since expired.
        if req["status"] != "PENDING":
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "This request is "
                    f"{req['status'].lower().replace('_', ' ')}."
                )
            }), 409

        if not req["token_valid"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "This verification link has expired. "
                    "Ask the student to submit a new request."
                )
            }), 410

        request_id = req["request_id"]

        # Lock this one OTP row so attempt counting is race-free.
        cursor.execute(
            """
            SELECT
                otp_id,
                code_hash,
                verified,
                locked,
                attempts,
                (expires_at > NOW()) AS is_valid
            FROM phone_change_otps
            WHERE request_id = %s AND channel = %s
            FOR UPDATE
            """,
            (request_id, channel)
        )

        otp = cursor.fetchone()

        if not otp:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Verification code not found"
            }), 404

        if otp["verified"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"The {channel} code has already been verified."
            }), 409

        if otp["locked"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    f"The {channel} code is locked after too many "
                    "incorrect attempts."
                )
            }), 423

        if not otp["is_valid"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "This code has expired. Submit a new request."
            }), 410

        # -----------------------------------------------------------
        # Wrong code: count the attempt, lock at the limit.
        # -----------------------------------------------------------

        if not otp_matches(
            request_id,
            channel,
            code,
            otp["code_hash"]
        ):
            attempts = int(otp["attempts"] or 0) + 1
            locked = attempts >= OTP_MAX_ATTEMPTS

            cursor.execute(
                """
                UPDATE phone_change_otps
                SET attempts = %s, locked = %s
                WHERE otp_id = %s
                """,
                (
                    attempts,
                    1 if locked else 0,
                    otp["otp_id"]
                )
            )

            write_audit(
                cursor,
                request_id,
                req["user_id"],
                "Parent",
                f"{channel}_OTP_LOCKED" if locked else f"{channel}_OTP_FAILED",
                {"attempts": attempts}
            )

            connection.commit()

            if locked:
                return jsonify({
                    "success": False,
                    "locked": True,
                    "message": (
                        f"Too many incorrect attempts. The {channel} "
                        "code is now locked."
                    ),
                    "attempts_left": 0
                }), 423

            return jsonify({
                "success": False,
                "message": "Incorrect code.",
                "attempts_left": OTP_MAX_ATTEMPTS - attempts
            }), 401

        # -----------------------------------------------------------
        # Correct code: one-time use. Invalidate immediately.
        # -----------------------------------------------------------

        cursor.execute(
            """
            UPDATE phone_change_otps
            SET
                verified = 1,
                verified_at = NOW(),
                code_hash = NULL
            WHERE otp_id = %s
            """,
            (otp["otp_id"],)
        )

        write_audit(
            cursor,
            request_id,
            req["user_id"],
            "Parent",
            f"{channel}_OTP_VERIFIED"
        )

        # -----------------------------------------------------------
        # Authentication is VERIFIED only when BOTH channels are done.
        # -----------------------------------------------------------

        cursor.execute(
            """
            SELECT channel, verified
            FROM phone_change_otps
            WHERE request_id = %s
            """,
            (request_id,)
        )

        states = {
            row["channel"]: bool(row["verified"])
            for row in cursor.fetchall()
        }

        auth_status = compute_auth_status(
            states.get("SMS", False),
            states.get("EMAIL", False)
        )

        newly_completed = False

        if auth_status == "VERIFIED":

            cursor.execute(
                """
                UPDATE phone_change_requests
                SET
                    auth_status = 'VERIFIED',
                    parent_verification_status = 'VERIFIED',
                    parent_verified_at = NOW()
                WHERE request_id = %s
                  AND auth_status <> 'VERIFIED'
                """,
                (request_id,)
            )

            newly_completed = cursor.rowcount == 1

            if newly_completed:
                write_audit(
                    cursor,
                    request_id,
                    req["user_id"],
                    "System",
                    "PARENT_AUTHENTICATION_COMPLETED"
                )

                # This request owes an AI assessment. The fact is
                # recorded inside the verification transaction, so it
                # can never be lost.
                mark_ai_assessment_owed(cursor, request_id)

                # Drop a durable inbox row for the mentor. The request
                # carries its mentor; fall back to the active assignment
                # in case the request predates assignment bookkeeping.
                mentor_id = req["mentor_id"] or get_active_mentor(
                    cursor, req["user_id"]
                )

                if mentor_id:
                    create_notification(
                        cursor,
                        mentor_id,
                        NOTIFY_PARENT_VERIFIED,
                        request_id,
                        inapp_parent_verified(
                            req["student_name"], request_id
                        )
                    )

        # -----------------------------------------------------------
        # COMMIT POINT
        #
        # The parent verification is durable from here on. The AI
        # assessment runs after this commit, in its own transaction, so
        # a failing model can no longer undo a successful verification.
        # -----------------------------------------------------------

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        app.logger.exception("Parent verify error")

        return jsonify({
            "success": False,
            "message": "Verification failed. Please try again."
        }), 500

    finally:
        close_db(cursor, connection)

    ai_status = None

    if newly_completed:
        # AI runs only after both OTPs are verified AND the
        # verification has been committed. A failure is recorded and
        # reported to the mentor; it never rolls the verification back.
        ai_outcome = execute_ai_assessment(
            request_id,
            req["user_id"],
            trigger="dual_otp"
        )

        ai_status = ai_outcome.get("status")

    if newly_completed and req["mentor_email"]:
        _notify_safely(
            "Mentor verification notice",
            send_email,
            req["mentor_email"],
            f"EduShield AI — Parent verification completed {request_id}",
            email_mentor_verification_complete(
                req["student_name"],
                request_id
            )
        )

    return jsonify({
        "success": True,
        "message": f"{channel} code verified.",
        "request_id": request_id,
        "sms_verified": states.get("SMS", False),
        "email_verified": states.get("EMAIL", False),
        "auth_status": auth_status,
        "ai_assessment_status": ai_status
    })


@app.route(
    "/parent/resend/<token>",
    methods=["POST"]
)
def parent_resend_code(token):
    """
    Re-issue fresh verification codes for a pending request.

    Used when a parent's code expired or locked before they could use it.
    Already-verified channels are never re-issued, so a full resend can
    never downgrade a completed verification. The parent link token is
    unchanged and still subject to its own expiry.
    """

    limited = rate_limit_exceeded(
        "parent-resend-ip",
        get_client_ip(),
        10,
        900,
        "Too many resend requests. Please try again later."
    )

    if limited:
        return limited

    limited = rate_limit_exceeded(
        "parent-resend-token",
        token,
        3,
        900,
        "Too many resend requests for this link. Please try again later."
    )

    if limited:
        return limited

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        req = _load_parent_request(cursor, token, for_update=True)

        if not req:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "This verification link is invalid."
            }), 404

        if req["status"] != "PENDING":
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "This request is "
                    f"{req['status'].lower().replace('_', ' ')}."
                )
            }), 409

        if not req["token_valid"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": (
                    "This verification link has expired. "
                    "Ask the student to submit a new request."
                )
            }), 410

        request_id = req["request_id"]

        # Only re-issue channels that are not yet verified.
        cursor.execute(
            """
            SELECT channel, verified
            FROM phone_change_otps
            WHERE request_id = %s
            """,
            (request_id,)
        )

        states = {
            row["channel"]: bool(row["verified"])
            for row in cursor.fetchall()
        }

        channels_to_resend = [
            channel
            for channel in CHANNELS
            if not states.get(channel, False)
        ]

        if not channels_to_resend:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Both codes are already verified."
            }), 409

        new_codes = {}

        for channel in channels_to_resend:
            code = generate_otp()
            new_codes[channel] = code

            cursor.execute(
                """
                UPDATE phone_change_otps
                SET
                    code_hash = %s,
                    expires_at = DATE_ADD(NOW(), INTERVAL %s MINUTE),
                    attempts = 0,
                    locked = 0
                WHERE request_id = %s
                  AND channel = %s
                  AND verified = 0
                """,
                (
                    hash_otp(request_id, channel, code),
                    OTP_TTL_MINUTES,
                    request_id,
                    channel
                )
            )

        write_audit(
            cursor,
            request_id,
            req["user_id"],
            "Parent",
            "OTP_RESENT",
            {"channels": channels_to_resend}
        )

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print("Parent resend error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Could not resend codes. Please try again."
        }), 500

    finally:
        close_db(cursor, connection)

    # Deliver the new codes after the commit. Never returned in the API.
    verify_url = f"{_base_url()}/parent/verify/{token}"

    delivery = {"sms": False, "email": False}

    if "SMS" in new_codes:
        try:
            parent_phone_e164 = normalize_phone_e164(req["parent_phone"])

            if not parent_phone_e164:
                raise DeliveryError("Parent phone number is not valid.")

            send_sms(
                parent_phone_e164,
                sms_parent_code_text(new_codes["SMS"])
            )
            delivery["sms"] = True

        except DeliveryError as e:
            print(f"⚠️ Parent SMS resend not delivered: {e}", flush=True)

    if "EMAIL" in new_codes:
        try:
            send_email(
                req["parent_email"],
                "EduShield AI — New Verification Code",
                email_parent_verification_body(
                    req["student_name"],
                    mask_phone(req["new_phone"]),
                    verify_url,
                    new_codes["EMAIL"]
                ),
                html=email_parent_verification_html(
                    req["student_name"],
                    mask_phone(req["new_phone"]),
                    verify_url,
                    new_codes["EMAIL"]
                )
            )
            delivery["email"] = True

        except DeliveryError as e:
            print(f"⚠️ Parent email resend not delivered: {e}", flush=True)

    return jsonify({
        "success": True,
        "message": "New codes sent.",
        "request_id": request_id,
        "resent": channels_to_resend,
        "delivery": delivery
    })


@app.route(
    "/parent/report/<token>",
    methods=["POST"]
)
def parent_report_not_me(token):
    """
    'This wasn't me': place the request on SECURITY HOLD.

    The request can no longer be approved. The mentor is alerted.
    """

    limited = rate_limit_exceeded(
        "parent-report-ip",
        get_client_ip(),
        10,
        60,
        "Too many requests. Please try again later."
    )

    if limited:
        return limited

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        req = _load_parent_request(cursor, token, for_update=True)

        if not req:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "This link is invalid."
            }), 404

        if req["status"] != "PENDING":
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "This request can no longer be changed."
            }), 409

        request_id = req["request_id"]

        cursor.execute(
            """
            UPDATE phone_change_requests
            SET
                status = 'SECURITY_HOLD',
                parent_token_expires_at = NOW()
            WHERE request_id = %s
              AND status = 'PENDING'
            """,
            (request_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "This request can no longer be changed."
            }), 409

        cursor.execute(
            """
            UPDATE phone_change_otps
            SET locked = 1, code_hash = NULL
            WHERE request_id = %s AND verified = 0
            """,
            (request_id,)
        )

        write_audit(
            cursor,
            request_id,
            req["user_id"],
            "Parent",
            "SECURITY_HOLD_RAISED",
            {"reported_by": "parent"}
        )

        # Notify the mentor in-app (as well as by email after commit).
        mentor_id = req["mentor_id"] or get_active_mentor(
            cursor, req["user_id"]
        )

        if mentor_id:
            create_notification(
                cursor,
                mentor_id,
                NOTIFY_SECURITY_HOLD,
                request_id,
                inapp_security_hold(req["student_name"], request_id)
            )

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print("Parent report error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Could not record your report. Please try again."
        }), 500

    finally:
        close_db(cursor, connection)

    if req["mentor_email"]:
        _notify_safely(
            "Mentor security alert",
            send_email,
            req["mentor_email"],
            f"EduShield AI — SECURITY HOLD {request_id}",
            email_mentor_security_hold(req["student_name"], request_id)
        )

    _notify_safely(
        "Student security notice",
        send_email,
        req["student_email"],
        f"EduShield AI — Security hold {request_id}",
        email_student_security_hold(req["student_name"], request_id)
    )

    return jsonify({
        "success": True,
        "message": (
            "Thank you. This request is on security hold and your "
            "mentor has been alerted."
        ),
        "request_id": request_id,
        "status": "SECURITY_HOLD"
    })


# -------------------------------------------------------------------
# Account activation (Phase 1)
#
# Imported students and mentors start with account_status =
# 'pending_activation' and no password. They prove control of their
# institutional email with a one-time code, then set their own password.
# The code is emailed only; it is never returned by the API and only its
# keyed hash is stored. Same rules as the parent OTPs: 5 minute expiry,
# 3 attempts then lock, one-time use.
# -------------------------------------------------------------------

_ACTIVATION_GENERIC = {
    "success": True,
    "message": (
        "If that ID matches a pending account, an activation code has "
        "been emailed."
    ),
}


@app.route("/api/auth/activate/request", methods=["POST"])
def request_account_activation():

    limited = rate_limit_exceeded(
        "activate-request-ip",
        get_client_ip(),
        10,
        900,
        "Too many activation requests. Please try again later."
    )
    if limited:
        return limited

    data = request.get_json(silent=True) or {}
    external_id = str(data.get("external_id", "")).strip()

    if not external_id:
        return jsonify({
            "success": False,
            "message": "external_id is required"
        }), 400

    connection = None
    cursor = None
    send_to = None
    code = None
    recipient_name = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT user_id, name, institutional_email, account_status
            FROM users
            WHERE external_id = %s
            """,
            (external_id,)
        )

        user = cursor.fetchone()

        # Unknown, already-active or disabled accounts get the same
        # generic reply so the endpoint cannot be used to enumerate IDs.
        if (
            not user
            or user.get("account_status") != "pending_activation"
            or not user.get("institutional_email")
        ):
            connection.rollback()
            return jsonify(_ACTIVATION_GENERIC), 200

        cursor.execute(
            """
            SELECT id
            FROM account_activation_otps
            WHERE user_id = %s
              AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)
            LIMIT 1
            """,
            (user["user_id"], ACTIVATION_RESEND_COOLDOWN_SECONDS)
        )

        if cursor.fetchone():
            connection.rollback()
            return jsonify(_ACTIVATION_GENERIC), 200

        # Only the newest code can be used.
        cursor.execute(
            """
            UPDATE account_activation_otps
            SET used = 1
            WHERE user_id = %s
              AND used = 0
            """,
            (user["user_id"],)
        )

        code = generate_otp()

        cursor.execute(
            """
            INSERT INTO account_activation_otps
            (
                user_id,
                code_hash,
                expires_at
            )
            VALUES
            (
                %s,
                %s,
                DATE_ADD(NOW(), INTERVAL %s MINUTE)
            )
            """,
            (
                user["user_id"],
                hash_otp(user["user_id"], ACTIVATION_CHANNEL, code),
                ACTIVATION_OTP_EXPIRY_MINUTES
            )
        )

        write_audit(
            cursor,
            None,
            user["user_id"],
            "System",
            "ACCOUNT_ACTIVATION_CODE_SENT"
        )

        connection.commit()

        send_to = user["institutional_email"]
        recipient_name = user["name"]

    except Exception:
        if connection:
            connection.rollback()

        app.logger.exception("Activation request failed")

        return jsonify({
            "success": False,
            "message": "Could not process activation request"
        }), 500

    finally:
        close_db(cursor, connection)

    _notify_safely(
        "Account activation email",
        send_email,
        send_to,
        "EduShield AI — Activate your account",
        email_account_activation_body(recipient_name, code)
    )

    return jsonify(_ACTIVATION_GENERIC), 200


@app.route("/api/auth/activate/verify", methods=["POST"])
def verify_account_activation():

    limited = rate_limit_exceeded(
        "activate-verify-ip",
        get_client_ip(),
        20,
        900,
        "Too many activation attempts. Please try again later."
    )
    if limited:
        return limited

    data = request.get_json(silent=True) or {}

    external_id = str(data.get("external_id", "")).strip()
    code = str(data.get("code", "")).strip()
    password = data.get("password") or ""
    confirm = data.get("confirm_password")

    if not external_id or not code:
        return jsonify({
            "success": False,
            "message": "external_id and code are required"
        }), 400

    if not is_valid_otp_format(code):
        return jsonify({
            "success": False,
            "message": "The activation code must be 6 digits"
        }), 400

    if confirm is not None and password != confirm:
        return jsonify({
            "success": False,
            "message": "Passwords do not match"
        }), 400

    if len(password) < ACTIVATION_MIN_PASSWORD_LENGTH:
        return jsonify({
            "success": False,
            "message": (
                f"Password must be at least "
                f"{ACTIVATION_MIN_PASSWORD_LENGTH} characters"
            )
        }), 400

    connection = None
    cursor = None

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT user_id, name, institutional_email, account_status
            FROM users
            WHERE external_id = %s
            """,
            (external_id,)
        )

        user = cursor.fetchone()

        if not user or user.get("account_status") != "pending_activation":
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "No pending activation for that ID"
            }), 404

        cursor.execute(
            """
            SELECT
                id,
                code_hash,
                attempts,
                locked,
                used,
                (expires_at > NOW()) AS is_valid
            FROM account_activation_otps
            WHERE user_id = %s
              AND used = 0
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (user["user_id"],)
        )

        otp = cursor.fetchone()

        if not otp:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "No active code. Request a new one."
            }), 410

        if otp["locked"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Too many incorrect attempts. Request a new code."
            }), 423

        if not otp["is_valid"]:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "The code has expired. Request a new one."
            }), 410

        if not otp_matches(
            user["user_id"], ACTIVATION_CHANNEL, code, otp["code_hash"]
        ):
            attempts = int(otp["attempts"] or 0) + 1
            locked = 1 if attempts >= ACTIVATION_MAX_ATTEMPTS else 0

            cursor.execute(
                """
                UPDATE account_activation_otps
                SET attempts = %s, locked = %s
                WHERE id = %s
                """,
                (attempts, locked, otp["id"])
            )

            connection.commit()

            if locked:
                return jsonify({
                    "success": False,
                    "message": (
                        "Too many incorrect attempts. Request a new code."
                    )
                }), 423

            return jsonify({
                "success": False,
                "message": "Incorrect code",
                "attempts_left": max(0, ACTIVATION_MAX_ATTEMPTS - attempts)
            }), 401

        # Correct code: activate the account.
        cursor.execute(
            """
            UPDATE account_activation_otps
            SET used = 1, code_hash = NULL
            WHERE id = %s
            """,
            (otp["id"],)
        )

        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s,
                account_status = 'active'
            WHERE user_id = %s
            """,
            (hash_password(password), user["user_id"])
        )

        write_audit(
            cursor,
            None,
            user["user_id"],
            "System",
            "ACCOUNT_ACTIVATED"
        )

        connection.commit()

    except Exception:
        if connection:
            connection.rollback()

        app.logger.exception("Activation verify failed")

        return jsonify({
            "success": False,
            "message": "Could not activate the account"
        }), 500

    finally:
        close_db(cursor, connection)

    return jsonify({
        "success": True,
        "message": "Account activated. You can now sign in."
    }), 200


# -------------------------------------------------------------------
# Admin portal API (Phase 1)
#
# Every route requires an authenticated admin. Bulk assignment and
# unassignment are audited. Counts are computed server-side.
# -------------------------------------------------------------------

@app.route("/api/admin/summary", methods=["GET"])
@require_auth(allowed_roles=["admin"])
def admin_summary():

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        def scalar(sql):
            cursor.execute(sql)
            row = cursor.fetchone() or {}
            return int(row.get("total") or 0)

        students_total = scalar(
            "SELECT COUNT(*) AS total FROM users WHERE role = 'student'"
        )
        students_active = scalar(
            "SELECT COUNT(*) AS total FROM users "
            "WHERE role = 'student' AND account_status = 'active'"
        )
        students_pending = scalar(
            "SELECT COUNT(*) AS total FROM users "
            "WHERE role = 'student' AND account_status = 'pending_activation'"
        )
        mentors_total = scalar(
            "SELECT COUNT(*) AS total FROM users WHERE role = 'mentor'"
        )
        unassigned = scalar(
            "SELECT COUNT(*) AS total FROM users u "
            "LEFT JOIN mentor_assignments m "
            "  ON u.user_id = m.student_id AND m.active = 1 "
            "WHERE u.role = 'student' AND m.assignment_id IS NULL"
        )
        open_requests = scalar(
            "SELECT COUNT(*) AS total FROM phone_change_requests "
            "WHERE status IN ('PENDING', 'SECURITY_HOLD')"
        )

        cursor.execute(
            """
            SELECT
                run_id,
                finished_at,
                students_read,
                students_created,
                students_updated,
                mentors_created,
                mentors_updated,
                assignments_created,
                assignments_updated,
                unassigned
            FROM sis_import_runs
            ORDER BY run_id DESC
            LIMIT 1
            """
        )
        last_import = cursor.fetchone()

        return jsonify({
            "success": True,
            "summary": {
                "students_total": students_total,
                "students_active": students_active,
                "students_pending": students_pending,
                "mentors_total": mentors_total,
                "unassigned_students": unassigned,
                "open_requests": open_requests,
                "last_import": serialize_record(last_import),
            }
        }), 200

    except Exception:
        app.logger.exception("Admin summary failed")

        return jsonify({
            "success": False,
            "message": "Failed to load summary"
        }), 500

    finally:
        close_db(cursor, connection)


@app.route("/api/admin/users", methods=["GET"])
@require_auth(allowed_roles=["admin"])
def admin_list_users():

    role = (request.args.get("role") or "").strip()
    status = (request.args.get("status") or "").strip()
    search = (request.args.get("q") or "").strip()

    clauses = []
    params = []

    if role:
        clauses.append("u.role = %s")
        params.append(role)

    if status:
        clauses.append("u.account_status = %s")
        params.append(status)

    if search:
        like = f"%{search}%"
        clauses.append(
            "(u.name LIKE %s OR u.external_id LIKE %s OR u.email LIKE %s)"
        )
        params.extend([like, like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                u.user_id,
                u.name,
                u.email,
                u.institutional_email,
                u.external_id,
                u.role,
                u.account_status,
                u.department,
                u.section,
                u.year,
                m.mentor_id
            FROM users u
            LEFT JOIN mentor_assignments m
                ON m.student_id = u.user_id AND m.active = 1
            """
            + where
            + " ORDER BY u.role, u.external_id",
            tuple(params)
        )

        users = cursor.fetchall()
        for item in users:
            serialize_record(item)

        return jsonify({
            "success": True,
            "count": len(users),
            "users": users
        }), 200

    except Exception:
        app.logger.exception("Admin user list failed")

        return jsonify({
            "success": False,
            "message": "Failed to load users"
        }), 500

    finally:
        close_db(cursor, connection)


@app.route("/api/admin/assignments/bulk", methods=["POST"])
@require_auth(allowed_roles=["admin"])
def admin_bulk_assign():

    data = request.get_json(silent=True) or {}
    assignments = data.get("assignments")
    dry_run = bool(data.get("dry_run"))

    if not isinstance(assignments, list) or not assignments:
        return jsonify({
            "success": False,
            "message": "assignments must be a non-empty list"
        }), 400

    admin_id = request.user["user_id"]

    connection = None
    cursor = None
    created = 0
    updated = 0
    failed = []

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        for item in assignments:
            student_id = str((item or {}).get("student_id", "")).strip()
            mentor_id = str((item or {}).get("mentor_id", "")).strip()

            if not student_id or not mentor_id:
                failed.append({
                    "student_id": student_id,
                    "message": "student_id and mentor_id are required"
                })
                continue

            cursor.execute(
                "SELECT user_id, role FROM users WHERE user_id = %s",
                (student_id,)
            )
            student = cursor.fetchone()

            if not student or student["role"] != "student":
                failed.append({
                    "student_id": student_id,
                    "message": "student not found"
                })
                continue

            cursor.execute(
                "SELECT user_id, role FROM users WHERE user_id = %s",
                (mentor_id,)
            )
            mentor = cursor.fetchone()

            if not mentor or mentor["role"] != "mentor":
                failed.append({
                    "student_id": student_id,
                    "message": "mentor not found"
                })
                continue

            cursor.execute(
                """
                SELECT mentor_id, active
                FROM mentor_assignments
                WHERE student_id = %s
                """,
                (student_id,)
            )
            existing = cursor.fetchone()

            if existing is None:
                created += 1
                if not dry_run:
                    cursor.execute(
                        """
                        INSERT INTO mentor_assignments
                        (student_id, mentor_id, active)
                        VALUES (%s, %s, 1)
                        """,
                        (student_id, mentor_id)
                    )

            elif (
                not existing.get("active")
                or existing["mentor_id"] != mentor_id
            ):
                updated += 1
                if not dry_run:
                    cursor.execute(
                        """
                        UPDATE mentor_assignments
                        SET mentor_id = %s, active = 1
                        WHERE student_id = %s
                        """,
                        (mentor_id, student_id)
                    )

            if not dry_run:
                write_audit(
                    cursor,
                    None,
                    student_id,
                    "Admin",
                    "MENTOR_ASSIGNED",
                    {"mentor_id": mentor_id, "admin_id": admin_id}
                )

        if not dry_run:
            connection.commit()
        else:
            connection.rollback()

    except Exception:
        if connection:
            connection.rollback()

        app.logger.exception("Bulk assign failed")

        return jsonify({
            "success": False,
            "message": "Failed to assign mentors"
        }), 500

    finally:
        close_db(cursor, connection)

    return jsonify({
        "success": True,
        "dry_run": dry_run,
        "created": created,
        "updated": updated,
        "failed": failed
    }), 200


@app.route("/api/admin/assignments/unassign", methods=["POST"])
@require_auth(allowed_roles=["admin"])
def admin_unassign():

    data = request.get_json(silent=True) or {}
    student_ids = data.get("student_ids")

    if not isinstance(student_ids, list) or not student_ids:
        return jsonify({
            "success": False,
            "message": "student_ids must be a non-empty list"
        }), 400

    admin_id = request.user["user_id"]

    connection = None
    cursor = None
    unassigned = 0

    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        for raw in student_ids:
            student_id = str(raw or "").strip()
            if not student_id:
                continue

            cursor.execute(
                """
                UPDATE mentor_assignments
                SET active = 0
                WHERE student_id = %s
                  AND active = 1
                """,
                (student_id,)
            )
            unassigned += cursor.rowcount

            write_audit(
                cursor,
                None,
                student_id,
                "Admin",
                "MENTOR_UNASSIGNED",
                {"admin_id": admin_id}
            )

        connection.commit()

    except Exception:
        if connection:
            connection.rollback()

        app.logger.exception("Unassign failed")

        return jsonify({
            "success": False,
            "message": "Failed to unassign mentors"
        }), 500

    finally:
        close_db(cursor, connection)

    return jsonify({
        "success": True,
        "unassigned": unassigned
    }), 200


# -------------------------------------------------------------------
# Admin: retry a failed AI assessment
#
# The AI assessment is required before a request can be approved. When
# the model is unavailable the request stays blocked and the failure is
# recorded. This endpoint re-runs the assessment.
#
# The retry is idempotent: one request owns exactly one assessment, so
# retrying updates that assessment instead of creating a second one.
# Mentor authorisation is untouched: only an admin can trigger a retry.
# -------------------------------------------------------------------

@app.route(
    "/api/admin/ai-assessments/<request_id>/retry",
    methods=["POST"]
)
@require_auth(allowed_roles=["admin"])
def admin_retry_ai_assessment(request_id):

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                p.request_id,
                p.user_id,
                p.auth_status,
                p.status,
                u.name AS student_name
            FROM phone_change_requests p
            JOIN users u
                ON u.user_id = p.user_id
            WHERE p.request_id = %s
            """,
            (request_id,)
        )

        req = cursor.fetchone()

        if not req:
            return jsonify({
                "success": False,
                "message": "Request not found"
            }), 404

        # The assessment only runs for a fully verified request.
        if req["auth_status"] != "VERIFIED":
            return jsonify({
                "success": False,
                "message": (
                    "The parent verification must be complete before an "
                    "assessment can be run."
                )
            }), 409

    except Exception:
        app.logger.exception("AI assessment retry lookup failed")

        return jsonify({
            "success": False,
            "message": "Failed to load the request"
        }), 500

    finally:
        close_db(cursor, connection)

    outcome = execute_ai_assessment(
        request_id,
        req["user_id"],
        trigger="admin_retry"
    )

    if not outcome["success"]:
        return jsonify({
            "success": False,
            "message": (
                "The risk assessment could not be produced. The request "
                "stays blocked until a retry succeeds."
            ),
            "ai_assessment_status": outcome["status"],
            "error": outcome["error"]
        }), 503

    return jsonify({
        "success": True,
        "message": "Risk assessment completed",
        "request_id": request_id,
        "ai_assessment_status": outcome["status"],
        "risk_score": outcome["result"]["risk_score"],
        "risk_level": outcome["result"]["risk_level"]
    }), 200


# -------------------------------------------------------------------
# DEMO ONLY: Authenticated/local-only OTP inbox
# -------------------------------------------------------------------

_LOOPBACK_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
_DEMO_INBOX_ENVIRONMENTS = {
    "development", "dev", "demo", "test", "testing", "local",
}


def _demo_inbox_denial():
    if OTP_DELIVERY_MODE != "demo":
        return jsonify({
            "success": False,
            "message": "Demo inbox only available in DEMO mode",
        }), 403

    # Never expose the inbox from a production deployment, even if the
    # process was started with the default (demo) delivery mode.
    environment = (
        os.getenv("EDUSHIELD_ENV") or "development"
    ).strip().lower()

    if environment not in _DEMO_INBOX_ENVIRONMENTS:
        return jsonify({
            "success": False,
            "message": "Demo inbox is not enabled in this environment",
        }), 403

    remote_address = (request.remote_addr or "").strip()

    if remote_address not in _LOOPBACK_ADDRESSES:
        return jsonify({
            "success": False,
            "message": "Demo inbox only available from localhost",
        }), 403

    return None


@app.route("/api/demo/sms-inbox", methods=["GET"])
@require_auth(allowed_roles=["admin", "mentor", "student"])
def demo_sms_inbox():
    denied = _demo_inbox_denial()
    if denied:
        return denied
    try:
        from otp_delivery import get_demo_sms_inbox
        inbox = get_demo_sms_inbox()
        return jsonify({"success": True, "mode": "DEMO_ONLY", "count": len(inbox), "inbox": inbox}), 200
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to retrieve demo inbox"}), 500


@app.route("/api/demo/sms-inbox/latest", methods=["GET"])
@require_auth(allowed_roles=["admin", "mentor", "student"])
def demo_sms_inbox_latest():
    denied = _demo_inbox_denial()
    if denied:
        return denied
    try:
        from otp_delivery import get_demo_sms_inbox
        inbox = get_demo_sms_inbox()
        if not inbox:
            return jsonify({"success": True, "mode": "DEMO_ONLY", "inbox": []}), 200
        return jsonify({"success": True, "mode": "DEMO_ONLY", "latest": inbox[-1]}), 200
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to retrieve demo inbox"}), 500


@app.route("/api/demo/email-inbox", methods=["GET"])
@require_auth(allowed_roles=["admin", "mentor", "student"])
def demo_email_inbox():
    denied = _demo_inbox_denial()
    if denied:
        return denied
    try:
        from otp_delivery import get_demo_email_inbox
        inbox = get_demo_email_inbox()
        return jsonify({"success": True, "mode": "DEMO_ONLY", "count": len(inbox), "inbox": inbox}), 200
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to retrieve demo inbox"}), 500


@app.route("/api/demo/email-inbox/latest", methods=["GET"])
@require_auth(allowed_roles=["admin", "mentor", "student"])
def demo_email_inbox_latest():
    denied = _demo_inbox_denial()
    if denied:
        return denied
    try:
        from otp_delivery import get_demo_email_inbox
        inbox = get_demo_email_inbox()
        if not inbox:
            return jsonify({"success": True, "mode": "DEMO_ONLY", "inbox": []}), 200
        return jsonify({"success": True, "mode": "DEMO_ONLY", "latest": inbox[-1]}), 200
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to retrieve demo inbox"}), 500


# -------------------------------------------------------------------
# Start server
# -------------------------------------------------------------------

from otp_delivery import validate_delivery_config

validate_delivery_config()

if __name__ == "__main__":
    app.run(
        host=os.getenv("EDUSHIELD_HOST", "127.0.0.1"),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        port=int(os.getenv("EDUSHIELD_PORT", "5000")),
    )
