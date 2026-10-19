from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import datetime
import json
import uuid
import math
import re
import os
from dotenv import load_dotenv
load_dotenv()

from ai.models.predict import predict_risk
import mysql.connector

from auth import generate_token, require_auth, verify_password, revoke_token
from config import DB_CONFIG
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
    email_decision,
    email_mentor_new_request,
    email_mentor_security_hold,
    email_mentor_verification_complete,
    email_parent_verification_body,
    email_student_security_hold,
    send_email,
    send_sms,
    sms_parent_code_text,
)


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
MODEL_VERSION = "logistic-regression-v1"

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

    except Exception as e:

        if connection:
            connection.rollback()

        return jsonify({
            "success": False,
            "message":
                "Login failed",
            "error":
                str(e)
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

    Best-effort: revocation is in-process, so the token is also short
    lived. A received token stays valid across restarts until a shared
    store is added.
    """

    revoke_token(request.user)

    return jsonify({
        "success": True,
        "message": "Logged out"
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

    risk_result = predict_risk(features)

    risk_score = max(
        0.0,
        min(100.0, float(risk_result["risk_score"]))
    )

    risk_level = determine_risk_level(risk_score)

    risk_factors = build_risk_factors(features)

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
        """,
        (
            request_id,
            risk_score,
            risk_level,
            json.dumps(risk_factors),
            MODEL_VERSION
        )
    )

    write_audit(
        cursor,
        request_id,
        user_id,
        "System",
        "AI_ASSESSMENT_GENERATED",
        {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "model_version": MODEL_VERSION
        }
    )

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_factors": risk_factors
    }


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
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                name,
                email,
                parent_email,
                parent_phone,
                phone_number,
                mentor_id
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        user_row = cursor.fetchone()

        if not user_row:
            return jsonify({
                "success": False,
                "message": "User not found"
            }), 404

        if not user_row["parent_email"] or not user_row["parent_phone"]:
            return jsonify({
                "success": False,
                "message":
                    "Parent SMS and email must both be registered "
                    "before a phone change can be requested"
            }), 400

        if not normalize_phone_e164(user_row["parent_phone"]):
            return jsonify({
                "success": False,
                "message":
                    "The registered parent phone number is not valid. "
                    "Contact the school to correct it."
            }), 400

        old_phone = user_row["phone_number"]

        if old_phone == new_phone:
            return jsonify({
                "success": False,
                "message": (
                    "New phone number must be different "
                    "from the current phone number"
                )
            }), 400

        # One open request per student keeps the flow simple to audit.
        cursor.execute(
            """
            SELECT request_id
            FROM phone_change_requests
            WHERE user_id = %s
              AND status = 'PENDING'
            LIMIT 1
            """,
            (user_id,)
        )

        if cursor.fetchone():
            return jsonify({
                "success": False,
                "message": (
                    "You already have an open phone-change request. "
                    "Wait for it to finish or cancel it first."
                )
            }), 409

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
                user_row["mentor_id"],
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

        send_sms(parent_phone_e164, sms_parent_code_text(sms_code))
        delivery["sms"] = True

    except DeliveryError as e:
        print(f"⚠️ Parent SMS not delivered: {e}", flush=True)

    try:
        send_email(
            parent_email,
            "EduShield AI — Verification Required",
            email_parent_verification_body(
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

    if user_row["mentor_id"]:
        mentor_email = _get_user_email(user_row["mentor_id"])

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
            SELECT user_id, status
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
                WHERE p.mentor_id = %s

                ORDER BY
                    p.requested_at DESC
                """,
                (user_id,)
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

    except Exception as e:

        return jsonify({
            "success": False,
            "message":
                "Failed to fetch phone change requests",
            "error":
                str(e)
        })

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

        if req["mentor_id"] != mentor_id:
            connection.rollback()
            return jsonify({
                "success": False,
                "message": "Not your request to review"
            }), 403

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

        if role == "mentor" and req["mentor_id"] != user_id:
            return jsonify({
                "success": False,
                "message": "Not your request to review"
            }), 403

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

def _load_parent_request(cursor, token):
    """Resolve a parent link token to its request. Only the hash is compared."""

    if not token:
        return None

    cursor.execute(
        """
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
        """,
        (hash_link_token(token),)
    )

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

        req = _load_parent_request(cursor, token)

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

                # AI runs only after both OTPs are verified.
                run_ai_assessment(
                    cursor,
                    request_id,
                    req["user_id"]
                )

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print("Parent verify error:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Verification failed. Please try again."
        }), 500

    finally:
        close_db(cursor, connection)

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
        "auth_status": auth_status
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

        req = _load_parent_request(cursor, token)

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

        req = _load_parent_request(cursor, token)

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
            """,
            (request_id,)
        )

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
# Start server
# -------------------------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        port=5000,
    )