from flask import (
    Flask,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
)
from functools import wraps
import os
import requests
import uuid

app = Flask(__name__)

# =========================================================
# CONFIGURATION
# =========================================================

# Server-to-server backend URL. Override with EDUSHIELD_BACKEND_URL when
# validating the backend through an HTTPS tunnel; never hardcode a tunnel.
BACKEND_URL = os.getenv(
    "EDUSHIELD_BACKEND_URL", "http://127.0.0.1:5000/api"
).rstrip("/")
BACKEND_ORIGIN = BACKEND_URL.rsplit("/api", 1)[0]
HTTP_TIMEOUT = (5, 20)
REQUEST_TIMEOUT = 10

# Send session cookies only over HTTPS. Off for local HTTP development;
# set EDUSHIELD_COOKIE_SECURE=1 in production.
COOKIE_SECURE = os.getenv("EDUSHIELD_COOKIE_SECURE", "0") == "1"

# Keep browser cookies aligned with the backend JWT lifetime. The backend
# defaults to 60 minutes (EDUSHIELD_TOKEN_TTL_MINUTES); a longer cookie would
# only leave an expired token in the browser and force a redirect.
TOKEN_TTL_MINUTES = int(os.getenv("EDUSHIELD_TOKEN_TTL_MINUTES", "60"))
AUTH_COOKIE_MAX_AGE = max(60, TOKEN_TTL_MINUTES * 60)


# =========================================================
# CSRF / ORIGIN PROTECTION
# =========================================================

def check_same_origin():
    """
    Reject cross-site requests to state-changing frontend routes.

    Defence-in-depth on top of SameSite=Strict cookies. When the browser
    sends an Origin or Referer, its host must match this request's host.
    When neither header is present we allow the request (an old browser
    on a same-origin form post); SameSite still blocks the cookie.
    """

    def host_of(value):
        if not value:
            return None
        return value.split("//", 1)[-1].split("/", 1)[0]

    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    expected = request.host

    for header_value in (origin, referer):
        if header_value:
            if host_of(header_value) != expected:
                return False
            return True

    return True


# =========================================================
# DEVICE IDENTIFICATION
# =========================================================

def get_device_id():
    #Give a new browser ID for the device

    device_id = request.cookies.get("edushield_device_id")

    if not device_id:
        device_id = str(uuid.uuid4())

    return device_id


# =========================================================
# CLIENT LOCATION
# =========================================================

def get_client_location():
    """
    Read GPS coordinates sent by the browser.

    No fallback to 0 is used.
    """

    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()
    DEFAULT_LOCATION = (17.3850, 78.4867)
    try:
        latitude = float(latitude)
        longitude = float(longitude)

        if not (-90 <= latitude <= 90):
            return None, None

        if not (-180 <= longitude <= 180):
            return None, None

        return latitude, longitude

    except (TypeError, ValueError):
        return None, None


# =========================================================
# AUTHORIZATION HEADERS
# =========================================================

def get_auth_headers(token):
    """
    Build authentication headers for backend API calls.
    """

    return {
        "Authorization": f"Bearer {token}",
        "X-Device-ID": get_device_id()
    }


# =========================================================
# SESSION / ROLE ENFORCEMENT
#
# The auth_token cookie is a JWT. We never trust its contents or
# the user_role cookie from the browser: we ask the backend to
# validate the token (signature + revocation) via /api/auth/me and
# use the role it returns. A cookie that merely exists is not
# enough.
# =========================================================

class AuthError(Exception):
    """Raised when a token is missing or invalid."""


def get_current_user():
    """
    Validate the auth_token cookie against the backend.

    Returns the trusted user dict, or None when there is no cookie,
    the token is rejected, or the backend is unreachable.
    """

    token = request.cookies.get("auth_token")

    if not token:
        return None

    try:
        response = requests.get(
            f"{BACKEND_URL}/auth/me",
            headers=get_auth_headers(token),
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return None

        data = safe_json(response)

        if not data.get("success"):
            return None

        return data.get("user") or None

    except requests.RequestException as e:
        print(
            "🔥 SESSION VALIDATION ERROR:",
            repr(e),
            flush=True
        )
        return None


def require_role(*allowed_roles):
    """
    Server-side guard for frontend routes.

    Redirects to /login when the session is missing or invalid, and
    to /dashboard when the authenticated user's role is not allowed.
    The trusted user is passed to the view as `current_user`.
    """

    def decorator(view):

        @wraps(view)
        def wrapper(*args, **kwargs):

            user = get_current_user()

            if not user:
                return redirect("/login")

            if allowed_roles and user.get("role") not in allowed_roles:
                return redirect("/dashboard")

            return view(*args, **kwargs, current_user=user)

        return wrapper

    return decorator



# =========================================================
# SAFE JSON
# =========================================================

def safe_json(response):
    """
    Safely parse backend JSON responses.
    """

    try:
        return response.json()
    except Exception:
        return {}


# =========================================================
# BACKEND CONNECTION TEST
# =========================================================

def backend_health_check():
    """
    Check whether the backend is reachable.
    """

    try:
        response = requests.get(
            f"{BACKEND_URL}/health",
            timeout=REQUEST_TIMEOUT
        )

        return response.ok

    except requests.RequestException:
        return False


# =========================================================
# HOME
# =========================================================

@app.route("/", methods=["GET"])
def index():
    return redirect("/login")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login_page():

    if request.method == "POST":

        if not check_same_origin():
            return render_template(
                "login.html",
                error="Request blocked for security reasons."
            ), 403

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        # -------------------------------------------------
        # VALIDATE INPUT
        # -------------------------------------------------

        if not email or not password:

            return render_template(
                "login.html",
                error="Email and password are required."
            )

        # -------------------------------------------------
        # DEVICE
        # -------------------------------------------------

        device_id = get_device_id()

        backend_endpoint = (
            f"{BACKEND_URL}/auth/login"
        )

        try:

            # -------------------------------------------------
            # CALL BACKEND
            # -------------------------------------------------

            response = requests.post(
                backend_endpoint,

                json={
                    "email": email,
                    "password": password
                },

                headers={
                    "X-Device-ID": device_id
                },

                timeout=REQUEST_TIMEOUT
            )

            data = safe_json(response)

            print(
                "Backend login status:",
                response.status_code,
                flush=True
            )

            # -------------------------------------------------
            # LOGIN SUCCESS
            # -------------------------------------------------

            if response.status_code == 200:

                token = data.get("token")
                user = data.get("user", {})

                if not token:

                    return render_template(
                        "login.html",
                        error=(
                            "Authentication server "
                            "did not return a token."
                        )
                    )

                # -------------------------------------------------
                # SAVE SESSION
                # -------------------------------------------------

                resp = make_response(
                    redirect("/dashboard")
                )

                resp.set_cookie(
                    "auth_token",
                    token,
                    httponly=True,
                    secure=COOKIE_SECURE,
                    max_age=AUTH_COOKIE_MAX_AGE,
                    samesite="Strict",
                    path="/"
                )

                resp.set_cookie(
                    "user_role",
                    user.get("role", "student"),
                    httponly=True,
                    secure=COOKIE_SECURE,
                    max_age=AUTH_COOKIE_MAX_AGE,
                    samesite="Strict",
                    path="/"
                )

                # -------------------------------------------------
                # PERSIST DEVICE ID
                # -------------------------------------------------

                resp.set_cookie(
                    "edushield_device_id",
                    device_id,
                    max_age=31536000,
                    httponly=True,
                    secure=COOKIE_SECURE,
                    samesite="Lax",
                    path="/"
                )

                return resp

            # -------------------------------------------------
            # LOGIN FAILURE
            # -------------------------------------------------

            error = data.get(
                "message",
                "Invalid credentials."
            )

            return render_template(
                "login.html",
                error=error
            )

        except requests.ConnectionError as e:

            print(
                "🔥 BACKEND CONNECTION ERROR:",
                repr(e),
                flush=True
            )

            return render_template(
                "login.html",
                error=(
                    "Backend server is unreachable. "
                    "Make sure port 5000 is running."
                )
            )

        except requests.Timeout as e:

            print(
                "🔥 BACKEND TIMEOUT:",
                repr(e),
                flush=True
            )

            return render_template(
                "login.html",
                error=(
                    "Backend server took too long to respond."
                )
            )

        except requests.RequestException as e:

            print(
                "🔥 BACKEND REQUEST ERROR:",
                repr(e),
                flush=True
            )

            return render_template(
                "login.html",
                error="Backend connection error. Please try again."
            )

        except Exception as e:

            print(
                "🔥 FRONTEND LOGIN ERROR:",
                repr(e),
                flush=True
            )

            return render_template(
                "login.html",
                error="An unexpected error occurred. Please try again."
            )

    return render_template("login.html")


# =========================================================
# STUDENT DASHBOARD
# =========================================================

@app.route("/student-dashboard", methods=["GET"])
@require_role("student")
def student_dashboard(current_user):

    token = request.cookies.get("auth_token")

    try:

        headers = get_auth_headers(token)

        response = requests.get(
            f"{BACKEND_URL}/phone-change-requests",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        data = safe_json(response)

        if response.status_code == 200:

            requests_list = data.get(
                "requests",
                []
            )

        else:

            requests_list = []

        return render_template(
            "student-dashboard.html",
            user_name=current_user.get("name") or "Student",
            user_id=current_user.get("user_id") or "",
            requests=requests_list
        )

    except requests.RequestException as e:

        print(
            "🔥 STUDENT DASHBOARD ERROR:",
            repr(e),
            flush=True
        )

        return render_template(
            "student-dashboard.html",
            user_name=current_user.get("name") or "Student",
            user_id=current_user.get("user_id") or "",
            requests=[],
            error="Unable to connect to backend server."
        )

    except Exception as e:

        print(
            "🔥 STUDENT DASHBOARD ERROR:",
            repr(e),
            flush=True
        )

        return render_template(
            "student-dashboard.html",
            user_name=current_user.get("name") or "Student",
            user_id=current_user.get("user_id") or "",
            requests=[],
            error="Unable to load your requests right now."
        )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout", methods=["GET"])
def logout():

    token = request.cookies.get("auth_token")

    # Best-effort server-side revocation of the current token.
    if token:
        try:
            requests.post(
                f"{BACKEND_URL}/auth/logout",
                headers=get_auth_headers(token),
                timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            print(
                "Logout revoke error:",
                repr(e),
                flush=True
            )

    response = make_response(
        redirect("/login")
    )

    response.delete_cookie("auth_token")
    response.delete_cookie("user_role")

    # IMPORTANT:
    # edushield_device_id is intentionally preserved.

    return response


# =========================================================
# REQUEST PHONE CHANGE
# =========================================================

@app.route("/request-phone-change", methods=["GET", "POST"])
@require_role("student")
def request_phone_change(current_user):
    token = request.cookies.get("auth_token")

    if request.method == "POST" and not check_same_origin():
        return render_template(
            "request-phone-change.html",
            old_phone="",
            new_phone="",
            error="Request blocked for security reasons."
        ), 403

    # -----------------------------------------------------
    # FETCH CURRENT USER'S PHONE NUMBER
    # -----------------------------------------------------
    def get_current_phone():
        try:
            headers = get_auth_headers(token)

            response = requests.get(
                f"{BACKEND_URL}/auth/me",
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

            data = safe_json(response)

            print(
                "Profile API status:",
                response.status_code,
                flush=True
            )

            if response.status_code != 200:
                return ""

            user = data.get("user") or {}
            return str(user.get("phone_number") or "")

        except requests.RequestException as e:
            print(
                "Current phone lookup failed:",
                repr(e),
                flush=True
            )
            return ""

    old_phone = get_current_phone()

    # -----------------------------------------------------
    # DISPLAY PHONE CHANGE FORM
    # -----------------------------------------------------
    if request.method == "GET":
        return render_template(
            "request-phone-change.html",
            old_phone=old_phone,
            new_phone=""
        )

    # -----------------------------------------------------
    # VALIDATE NEW PHONE NUMBER
    # -----------------------------------------------------
    new_phone = "".join(
        ch for ch in request.form.get("new_phone", "").strip()
        if ch.isdigit()
    )

    if len(new_phone) != 10:
        return render_template(
            "request-phone-change.html",
            old_phone=old_phone,
            new_phone=new_phone,
            error="Phone number must contain exactly 10 digits."
        )

    # -----------------------------------------------------
    # CLIENT GPS LOCATION (OPTIONAL RISK SIGNAL)
    # -----------------------------------------------------
    latitude, longitude = get_client_location()

    # -----------------------------------------------------
    # SUBMIT PHONE CHANGE REQUEST TO BACKEND
    # -----------------------------------------------------
    try:
        headers = get_auth_headers(token)

        if latitude is not None and longitude is not None:
            headers["X-Client-Latitude"] = str(latitude)
            headers["X-Client-Longitude"] = str(longitude)

        response = requests.post(
            f"{BACKEND_URL}/phone-change-requests",
            json={"new_phone": new_phone},
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        data = safe_json(response)

        print(
            "Phone change status:",
            response.status_code,
            flush=True
        )

        if response.status_code == 201:
            request_id = data.get("request_id")

            if not request_id:
                return render_template(
                    "request-phone-change.html",
                    old_phone=old_phone,
                    new_phone=new_phone,
                    error="Backend did not return a request ID."
                )

            return redirect("/student-dashboard")

        return render_template(
            "request-phone-change.html",
            old_phone=old_phone,
            new_phone=new_phone,
            error=data.get(
                "message",
                "Failed to create phone change request."
            )
        )

    except requests.ConnectionError:
        error = "Backend server is unreachable."

    except requests.Timeout:
        error = "Backend server took too long to respond."

    except requests.RequestException as e:
        print(
            "Phone change backend error:",
            repr(e),
            flush=True
        )
        error = "Backend connection error. Please try again."

    except Exception as e:
        print(
            "Phone change route error:",
            repr(e),
            flush=True
        )
        error = "An unexpected error occurred."

    return render_template(
        "request-phone-change.html",
        old_phone=old_phone,
        new_phone=new_phone,
        error=error
    )

# =========================================================
# MENTOR DASHBOARD
# =========================================================

@app.route(
    "/mentor-dashboard",
    methods=["GET"]
)
@require_role("mentor")
def mentor_dashboard(current_user):

    token = request.cookies.get("auth_token")

    status_filter = request.args.get(
        "status",
        "all"
    ).upper()

    try:

        headers = get_auth_headers(token)

        response = requests.get(
            f"{BACKEND_URL}/phone-change-requests",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        data = safe_json(response)

        if response.status_code == 200:

            requests_list = data.get(
                "requests",
                []
            )

            if status_filter != "ALL":

                requests_list = [
                    req
                    for req in requests_list
                    if req.get(
                        "status",
                        ""
                    ).upper() == status_filter
                ]

        else:

            requests_list = []

        return render_template(
            "mentor-dashboard.html",
            mentor_name=current_user.get("name") or "Mentor",
            mentor_id=current_user.get("user_id") or "",
            requests=requests_list,
            current_filter=status_filter
        )

    except requests.RequestException as e:

        print(
            "🔥 MENTOR DASHBOARD ERROR:",
            repr(e),
            flush=True
        )

        return render_template(
            "mentor-dashboard.html",
            mentor_name=current_user.get("name") or "Mentor",
            mentor_id=current_user.get("user_id") or "",
            requests=[],
            current_filter=status_filter,
            error="Unable to connect to backend server."
        )

    except Exception as e:

        print(
            "🔥 MENTOR DASHBOARD ERROR:",
            repr(e),
            flush=True
        )

        return render_template(
            "mentor-dashboard.html",
            mentor_name=current_user.get("name") or "Mentor",
            mentor_id=current_user.get("user_id") or "",
            requests=[],
            current_filter=status_filter,
            error="Unable to load the dashboard right now."
        )


# =========================================================
# NOTIFICATIONS (BFF proxy for the in-app inbox)
#
# The backend owns all ownership checks. These routes only relay the
# caller's own auth token, so they can never widen access.
# =========================================================

@app.route(
    "/notifications",
    methods=["GET"]
)
@require_role("student", "mentor", "admin")
def notifications_feed(current_user):

    token = request.cookies.get("auth_token")

    try:
        response = requests.get(
            f"{BACKEND_URL}/notifications",
            headers=get_auth_headers(token),
            timeout=REQUEST_TIMEOUT
        )

        return jsonify(safe_json(response)), response.status_code

    except requests.RequestException as e:
        print("🔥 NOTIFICATIONS FEED ERROR:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "notifications": [],
            "unread": 0,
            "message": "Backend server is unreachable."
        }), 502


@app.route(
    "/notifications/<int:notification_id>/read",
    methods=["POST"]
)
@require_role("student", "mentor", "admin")
def notifications_mark_read(notification_id, current_user):

    token = request.cookies.get("auth_token")

    if not check_same_origin():
        return jsonify({
            "success": False,
            "message": "Request blocked for security reasons."
        }), 403

    try:
        response = requests.post(
            f"{BACKEND_URL}/notifications/{notification_id}/read",
            headers=get_auth_headers(token),
            timeout=REQUEST_TIMEOUT
        )

        return jsonify(safe_json(response)), response.status_code

    except requests.RequestException as e:
        print("🔥 NOTIFICATION READ ERROR:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Backend server is unreachable."
        }), 502


# =========================================================
# PARENT VERIFICATION PROXY
# =========================================================

def proxy_parent_request(path):
    url = f"{BACKEND_ORIGIN}/{path}"

    try:
        if request.method == "GET":
            upstream = requests.get(
                url,
                headers={"Accept": request.headers.get("Accept", "*/*")},
                timeout=HTTP_TIMEOUT
            )
        else:
            upstream = requests.post(
                url,
                json=request.get_json(silent=True),
                headers={"Accept": request.headers.get("Accept", "*/*")},
                timeout=HTTP_TIMEOUT
            )
    except requests.RequestException as e:
        print("🔥 PARENT VERIFY PROXY ERROR:", repr(e), flush=True)
        return (
            "Parent verification service is temporarily unavailable.",
            502,
            {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}
        )

    response = make_response(upstream.content, upstream.status_code)
    response.headers["Content-Type"] = upstream.headers.get(
        "Content-Type", "text/html; charset=utf-8"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/parent/verify/<token>", methods=["GET"])
def proxy_parent_page(token):
    return proxy_parent_request(f"parent/verify/{token}")


@app.route("/parent/verify/<token>/<channel>", methods=["POST"])
def proxy_parent_code(token, channel):
    return proxy_parent_request(f"parent/verify/{token}/{channel}")


@app.route("/parent/resend/<token>", methods=["POST"])
def proxy_parent_resend(token):
    return proxy_parent_request(f"parent/resend/{token}")


@app.route("/parent/report/<token>", methods=["POST"])
def proxy_parent_report(token):
    return proxy_parent_request(f"parent/report/{token}")


# =========================================================
# REQUEST DETAIL
# =========================================================

@app.route(
    "/request-detail/<request_id>",
    methods=["GET", "POST"]
)
@require_role("student", "mentor", "admin")
def request_detail(request_id, current_user):

    token = request.cookies.get("auth_token")

    # =====================================================
    # MENTOR DECISION
    # =====================================================

    if request.method == "POST":

        if not check_same_origin():
            return redirect("/dashboard")

        decision = request.form.get(
            "decision",
            ""
        ).strip()

        reason = request.form.get(
            "reason",
            ""
        ).strip()

        try:

            headers = get_auth_headers(token)

            response = requests.patch(
                f"{BACKEND_URL}/phone-change-requests/{request_id}",

                json={
                    "decision": decision,
                    "reason": reason
                },

                headers=headers,

                timeout=REQUEST_TIMEOUT
            )

            data = safe_json(response)

            if response.status_code == 200:

                return redirect(
                    f"/request-detail/{request_id}?success=true"
                )

            error = data.get(
                "message",
                "Failed to process decision."
            )

            return render_template(
                "request-detail.html",
                error=error,
                request={
                    "request_id": request_id
                }
            )

        except requests.RequestException as e:

            print(
                "🔥 REQUEST DECISION ERROR:",
                repr(e),
                flush=True
            )

            return render_template(
                "request-detail.html",
                error="Unable to connect to backend server.",
                request={
                    "request_id": request_id
                }
            )

        except Exception as e:

            print(
                "🔥 REQUEST DECISION ERROR:",
                repr(e),
                flush=True
            )

            return render_template(
                "request-detail.html",
                error="Unable to process the decision right now.",
                request={
                    "request_id": request_id
                }
            )

    # =====================================================
    # LOAD REQUEST DETAILS
    # =====================================================

    try:

        headers = get_auth_headers(token)

        response = requests.get(
            f"{BACKEND_URL}/phone-change-requests/{request_id}",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:

            data = safe_json(response)

            return (
                data.get(
                    "message",
                    "Request not found."
                ),
                response.status_code
            )

        data = safe_json(response)

        req = data.get(
            "request",
            {}
        )

        # The backend returns these keys as JSON null until the AI
        # assessment has run (i.e. before both parent OTPs verify).
        # A present-but-null key defeats the dict default, so coerce
        # falsy values to an empty dict before any .get() calls.
        security = data.get(
            "security_context"
        ) or {}

        ai = data.get(
            "ai_assessment"
        ) or {}

        # =================================================
        # RISK FACTOR DETAILS
        # =================================================

        risk_factor_details = []

        if security:

            # 1. KNOWN DEVICE

            if security.get("known_device") == 0:

                risk_factor_details.append({
                    "name": "Unknown Device",
                    "level": "warning",
                    "description": (
                        "Login from a device we "
                        "haven't seen before"
                    )
                })

            # 2. LOCATION DEVIATION

            try:
                location_deviation = float(
                    security.get(
                        "location_deviation",
                        0
                    )
                )
            except (TypeError, ValueError):
                location_deviation = 0.0

            if location_deviation > 0.6:

                risk_factor_details.append({
                    "name": "Location Deviation",
                    "level": "warning",
                    "description": (
                        "Request from unusual "
                        "location "
                        f"(deviation: "
                        f"{location_deviation:.2f})"
                    )
                })

            # 3. FAILED LOGIN COUNT

            try:
                failed_login_count = int(
                    security.get(
                        "failed_login_count",
                        0
                    )
                )
            except (TypeError, ValueError):
                failed_login_count = 0

            if failed_login_count > 2:

                risk_factor_details.append({
                    "name": "Failed Login Attempts",
                    "level": "warning",
                    "description": (
                        "Multiple failed login "
                        f"attempts "
                        f"({failed_login_count} attempts)"
                    )
                })

            # 4. RECENT PASSWORD RESET

            if security.get(
                "recent_password_reset"
            ) == 1:

                risk_factor_details.append({
                    "name": "Recent Password Reset",
                    "level": "warning",
                    "description": (
                        "Password was recently changed"
                    )
                })

            # 5. MFA

            if security.get(
                "mfa_verified"
            ) == 0:

                risk_factor_details.append({
                    "name": "MFA Not Verified",
                    "level": "warning",
                    "description": (
                        "Two-factor authentication "
                        "has not been recently verified"
                    )
                })

            # 6. PHONE CHANGE FREQUENCY

            try:
                phone_change_frequency = int(
                    security.get(
                        "phone_change_frequency",
                        0
                    )
                )
            except (TypeError, ValueError):
                phone_change_frequency = 0

            if phone_change_frequency > 2:

                risk_factor_details.append({
                    "name": "Frequent Phone Changes",
                    "level": "warning",
                    "description": (
                        "Student has changed phone "
                        f"{phone_change_frequency} "
                        "times "
                        "(threshold: 2)"
                    )
                })

            # 7. LOGIN TIME DEVIATION

            try:
                login_time_deviation = float(
                    security.get(
                        "login_time_deviation",
                        0
                    )
                )
            except (TypeError, ValueError):
                login_time_deviation = 0.0

            if login_time_deviation > 0.6:

                risk_factor_details.append({
                    "name": "Login Time Deviation",
                    "level": "warning",
                    "description": (
                        "Login at unusual time "
                        f"(deviation: "
                        f"{login_time_deviation:.2f})"
                    )
                })

        # =================================================
        # AI ASSESSMENT
        # =================================================

        if ai.get("risk_score") is not None:

            try:

                ai["risk_score"] = float(
                    ai["risk_score"]
                )

            except (TypeError, ValueError):
                pass

        if ai.get("risk_level"):

            ai["risk_level"] = str(
                ai["risk_level"]
            ).upper()

        return render_template(
            "request-detail.html",
            request=req,
            security_context=security,
            ai_assessment=ai,
            risk_factor_details=risk_factor_details,
            otp_channels=data.get("otp_channels", [])
        )

    except requests.RequestException as e:

        print(
            "🔥 REQUEST DETAIL ERROR:",
            repr(e),
            flush=True
        )

        return (
            "Unable to load request details right now.",
            500
        )

    except Exception as e:

        print(
            "🔥 REQUEST DETAIL ERROR:",
            repr(e),
            flush=True
        )

        return (
            "Unable to load request details right now.",
            500
        )


# =========================================================
# DASHBOARD ROUTER
# =========================================================

@app.route(
    "/dashboard",
    methods=["GET"]
)
def dashboard():

    # Validate the session and use the backend-confirmed role,
    # never the browser-controlled user_role cookie.
    user = get_current_user()

    if not user:
        return redirect("/login")

    role = user.get("role")

    if role == "student":
        return redirect("/student-dashboard")

    if role == "admin":
        return redirect("/admin-dashboard")

    if role == "mentor":
        return redirect("/mentor-dashboard")

    return redirect("/login")


# =========================================================
# CANCEL PHONE CHANGE (student)
# =========================================================

@app.route(
    "/cancel-phone-change/<request_id>",
    methods=["POST"]
)
@require_role("student")
def cancel_phone_change(request_id, current_user):

    token = request.cookies.get("auth_token")

    if not check_same_origin():
        return redirect("/student-dashboard")

    try:
        requests.post(
            f"{BACKEND_URL}/phone-change-requests/{request_id}/cancel",
            headers=get_auth_headers(token),
            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as e:
        print("🔥 CANCEL REQUEST ERROR:", repr(e), flush=True)

    return redirect("/student-dashboard")


# =========================================================
# DELETE PHONE CHANGE (student soft delete)
# =========================================================

@app.route(
    "/delete-phone-change/<request_id>",
    methods=["POST"]
)
@require_role("student")
def delete_phone_change(request_id, current_user):

    token = request.cookies.get("auth_token")

    if not check_same_origin():
        return redirect("/student-dashboard")

    try:
        requests.post(
            f"{BACKEND_URL}/phone-change-requests/{request_id}/delete",
            headers=get_auth_headers(token),
            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as e:
        print("🔥 DELETE REQUEST ERROR:", repr(e), flush=True)

    return redirect("/student-dashboard")


# =========================================================
# NOTIFY MENTOR (student)
#
# Relays the request to the backend and returns its JSON status so the
# dashboard can show the outcome (including the 429 rate limit) without
# a full page reload.
# =========================================================

@app.route(
    "/notify-mentor/<request_id>",
    methods=["POST"]
)
@require_role("student")
def notify_mentor(request_id, current_user):

    token = request.cookies.get("auth_token")

    if not check_same_origin():
        return jsonify({
            "success": False,
            "message": "Request blocked for security reasons."
        }), 403

    try:
        response = requests.post(
            f"{BACKEND_URL}/phone-change-requests/{request_id}/notify-mentor",
            headers=get_auth_headers(token),
            timeout=REQUEST_TIMEOUT
        )

        return jsonify(safe_json(response)), response.status_code

    except requests.RequestException as e:
        print("🔥 NOTIFY MENTOR ERROR:", repr(e), flush=True)

        return jsonify({
            "success": False,
            "message": "Backend server is unreachable."
        }), 502


# =========================================================
# ACCOUNT ACTIVATION (Phase 1)
#
# Two steps on one page: request a code, then enter it with a new
# password. The frontend only relays; the backend owns all rules.
# =========================================================

@app.route("/activate", methods=["GET", "POST"])
def activate():
    if request.method == "POST":
        if not check_same_origin():
            return render_template(
                "activate.html",
                error="Request blocked for security reasons."
            ), 403

        step = request.form.get("step", "request").strip()
        external_id = request.form.get("external_id", "").strip()

        if step == "request":
            if not external_id:
                return render_template(
                    "activate.html",
                    error="Enter your Student or Mentor ID."
                )

            try:
                response = requests.post(
                    f"{BACKEND_URL}/auth/activate/request",
                    json={"external_id": external_id},
                    timeout=REQUEST_TIMEOUT
                )
                data = safe_json(response)

                return render_template(
                    "activate.html",
                    step="verify",
                    external_id=external_id,
                    info=data.get(
                        "message",
                        "If that ID matches a pending account, an "
                        "activation code has been emailed."
                    )
                )

            except requests.RequestException as e:
                print("🔥 ACTIVATION REQUEST ERROR:", repr(e), flush=True)
                return render_template(
                    "activate.html",
                    error="Backend server is unreachable."
                )

        # step == "verify"
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if password != confirm:
            return render_template(
                "activate.html",
                step="verify",
                external_id=external_id,
                error="Passwords do not match."
            )

        try:
            response = requests.post(
                f"{BACKEND_URL}/auth/activate/verify",
                json={
                    "external_id": external_id,
                    "code": code,
                    "password": password,
                    "confirm_password": confirm
                },
                timeout=REQUEST_TIMEOUT
            )
            data = safe_json(response)

            if response.status_code == 200:
                return render_template(
                    "activate.html",
                    step="done"
                )

            return render_template(
                "activate.html",
                step="verify",
                external_id=external_id,
                error=data.get("message", "Activation failed.")
            )

        except requests.RequestException as e:
            print("🔥 ACTIVATION VERIFY ERROR:", repr(e), flush=True)
            return render_template(
                "activate.html",
                step="verify",
                external_id=external_id,
                error="Backend server is unreachable."
            )

    return render_template("activate.html", step="request")


# =========================================================
# ADMIN PORTAL (Phase 1)
# =========================================================

def _admin_headers():
    """
    Return auth headers for the current request.

    Callers must already be guarded by @require_role("admin"), which
    has validated the token and role against the backend.
    """

    return get_auth_headers(request.cookies.get("auth_token"))


@app.route("/admin-dashboard", methods=["GET"])
@require_role("admin")
def admin_dashboard(current_user):
    headers = _admin_headers()

    summary = {}
    error = None

    try:
        response = requests.get(
            f"{BACKEND_URL}/admin/summary",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        data = safe_json(response)

        if response.status_code == 200:
            summary = data.get("summary", {})
        else:
            error = data.get("message", "Failed to load summary.")

    except requests.RequestException as e:
        print("🔥 ADMIN SUMMARY ERROR:", repr(e), flush=True)
        error = "Unable to connect to backend server."

    return render_template(
        "admin-dashboard.html",
        summary=summary,
        error=error
    )


@app.route("/admin-users", methods=["GET"])
@require_role("admin")
def admin_users(current_user):
    headers = _admin_headers()

    role = request.args.get("role", "").strip()
    status = request.args.get("status", "").strip()
    query = request.args.get("q", "").strip()

    users = []
    error = None

    try:
        response = requests.get(
            f"{BACKEND_URL}/admin/users",
            headers=headers,
            params={"role": role, "status": status, "q": query},
            timeout=REQUEST_TIMEOUT
        )
        data = safe_json(response)

        if response.status_code == 200:
            users = data.get("users", [])
        else:
            error = data.get("message", "Failed to load users.")

    except requests.RequestException as e:
        print("🔥 ADMIN USERS ERROR:", repr(e), flush=True)
        error = "Unable to connect to backend server."

    return render_template(
        "admin-users.html",
        users=users,
        role=role,
        status=status,
        query=query,
        error=error
    )


def _parse_assignment_lines(raw):
    """Turn 'STU,MEN' lines into a list of assignment dicts."""

    assignments = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.replace("\t", ",").split(",")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        assignments.append({
            "student_id": parts[0],
            "mentor_id": parts[1],
        })
    return assignments


def _parse_id_lines(raw):
    return [line.strip() for line in raw.splitlines() if line.strip()]


@app.route("/admin-assign", methods=["GET", "POST"])
@require_role("admin")
def admin_assign(current_user):
    headers = _admin_headers()

    message = None
    error = None

    if request.method == "POST":
        if not check_same_origin():
            return render_template(
                "admin-assign.html",
                error="Request blocked for security reasons."
            ), 403

        action = request.form.get("action", "assign").strip()

        try:
            if action == "assign":
                assignments = _parse_assignment_lines(
                    request.form.get("assignments", "")
                )
                if not assignments:
                    error = "Enter at least one 'student_id,mentor_id' line."
                else:
                    response = requests.post(
                        f"{BACKEND_URL}/admin/assignments/bulk",
                        json={"assignments": assignments},
                        headers=headers,
                        timeout=REQUEST_TIMEOUT
                    )
                    data = safe_json(response)

                    if response.status_code == 200:
                        message = (
                            f"Assigned: {data.get('created', 0)} new, "
                            f"{data.get('updated', 0)} updated, "
                            f"{len(data.get('failed', []))} failed."
                        )
                    else:
                        error = data.get("message", "Bulk assign failed.")

            elif action == "unassign":
                student_ids = _parse_id_lines(
                    request.form.get("student_ids", "")
                )
                if not student_ids:
                    error = "Enter at least one student ID."
                else:
                    response = requests.post(
                        f"{BACKEND_URL}/admin/assignments/unassign",
                        json={"student_ids": student_ids},
                        headers=headers,
                        timeout=REQUEST_TIMEOUT
                    )
                    data = safe_json(response)

                    if response.status_code == 200:
                        message = (
                            f"Unassigned {data.get('unassigned', 0)} student(s)."
                        )
                    else:
                        error = data.get("message", "Unassign failed.")

        except requests.RequestException as e:
            print("🔥 ADMIN ASSIGN ERROR:", repr(e), flush=True)
            error = "Unable to connect to backend server."

    return render_template(
        "admin-assign.html",
        message=message,
        error=error
    )


# =========================================================
# START FRONTEND SERVER
# =========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("EDU-SHIELD FRONTEND")
    print("=" * 60)
    print("Backend:", BACKEND_URL)
    print("Frontend (development server): http://127.0.0.1:5002")
    print("Do not use this server in production; run it under a WSGI server.")
    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=5002,
        debug=False,
        threaded=True,
    )
