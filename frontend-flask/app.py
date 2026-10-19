from flask import Flask, render_template, redirect, request, make_response
import os
import requests
import uuid

app = Flask(__name__)

# =========================================================
# CONFIGURATION
# =========================================================

BACKEND_URL = "http://127.0.0.1:5000/api"
HTTP_TIMEOUT = (5, 20)
REQUEST_TIMEOUT = 10

# Send session cookies only over HTTPS. Off for local HTTP development;
# set EDUSHIELD_COOKIE_SECURE=1 in production.
COOKIE_SECURE = os.getenv("EDUSHIELD_COOKIE_SECURE", "0") == "1"


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
        # GET GPS
        # -------------------------------------------------

        latitude, longitude = get_client_location()

        if latitude is None or longitude is None:

            return render_template(
                "login.html",
                error="Valid location is required to login."
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
                    "X-Device-ID": device_id,
                    "X-Client-Latitude": str(latitude),
                    "X-Client-Longitude": str(longitude)
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
                    max_age=28800,
                    samesite="Strict",
                    path="/"
                )

                resp.set_cookie(
                    "user_role",
                    user.get("role", "student"),
                    httponly=True,
                    secure=COOKIE_SECURE,
                    max_age=28800,
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
                error=f"Backend connection error: {e}"
            )

        except Exception as e:

            print(
                "🔥 FRONTEND LOGIN ERROR:",
                repr(e),
                flush=True
            )

            return render_template(
                "login.html",
                error=str(e)
            )

    return render_template("login.html")


# =========================================================
# STUDENT DASHBOARD
# =========================================================

@app.route("/student-dashboard", methods=["GET"])
def student_dashboard():

    token = request.cookies.get("auth_token")

    if not token:
        return redirect("/login")

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
            user_name="Rahul",
            user_id="S1024",
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
            user_name="Rahul",
            user_id="S1024",
            requests=[],
            error="Unable to connect to backend server."
        )

    except Exception as e:

        return render_template(
            "student-dashboard.html",
            user_name="Rahul",
            user_id="S1024",
            requests=[],
            error=str(e)
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
def request_phone_change():
    token = request.cookies.get("auth_token")

    if not token:
        return redirect("/login")

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
    # VALIDATE CLIENT GPS LOCATION
    # -----------------------------------------------------
    latitude, longitude = get_client_location()

    if latitude is None or longitude is None:
        return render_template(
            "request-phone-change.html",
            old_phone=old_phone,
            new_phone=new_phone,
            error="Valid location is required to submit a phone change request."
        )

    # -----------------------------------------------------
    # SUBMIT PHONE CHANGE REQUEST TO BACKEND
    # -----------------------------------------------------
    try:
        headers = get_auth_headers(token)

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
        error = f"Backend connection error: {e}"

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
def mentor_dashboard():

    token = request.cookies.get("auth_token")

    if not token:
        return redirect("/login")

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
            mentor_name="Dr. Harsha",
            mentor_id="M021",
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
            mentor_name="Dr. Harsha",
            mentor_id="M021",
            requests=[],
            current_filter=status_filter,
            error="Unable to connect to backend server."
        )

    except Exception as e:

        return render_template(
            "mentor-dashboard.html",
            mentor_name="Dr. Harsha",
            mentor_id="M021",
            requests=[],
            current_filter=status_filter,
            error=str(e)
        )


# =========================================================
# REQUEST DETAIL
# =========================================================

@app.route(
    "/request-detail/<request_id>",
    methods=["GET", "POST"]
)
def request_detail(request_id):

    token = request.cookies.get("auth_token")

    if not token:
        return redirect("/login")

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

            return render_template(
                "request-detail.html",
                error=str(e),
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

        security = data.get(
            "security_context",
            {}
        )

        ai = data.get(
            "ai_assessment",
            {}
        )

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
            f"Error connecting to backend: {e}",
            500
        )

    except Exception as e:

        return (
            f"Error: {e}",
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

    token = request.cookies.get(
        "auth_token"
    )

    role = request.cookies.get(
        "user_role"
    )

    if not token:
        return redirect("/login")

    if role == "student":
        return redirect("/student-dashboard")

    return redirect("/mentor-dashboard")


# =========================================================
# CANCEL PHONE CHANGE (student)
# =========================================================

@app.route(
    "/cancel-phone-change/<request_id>",
    methods=["POST"]
)
def cancel_phone_change(request_id):

    token = request.cookies.get("auth_token")

    if not token:
        return redirect("/login")

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
# START FRONTEND SERVER
# =========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("EDU-SHIELD FRONTEND")
    print("=" * 60)
    print("Backend:", BACKEND_URL)
    print("Frontend: https://0.0.0.0:5002")
    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=5002,
        debug=False,
        threaded=True,
    )
