from flask import Flask, request, jsonify
import sys
from pathlib import Path


# ============================================================
# PYTHON PATH
# ============================================================

# Add backend directory to Python path
BACKEND_DIR = Path(__file__).resolve().parents[2]

sys.path.insert(
    0,
    str(BACKEND_DIR)
)


# Import trained AI risk prediction
from ai.models.predict import predict_risk


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

RISK_THRESHOLD = 50

MODEL_VERSION = "1.0"


# ============================================================
# AUTHENTICATION FLOW
# ============================================================

def determine_authentication_flow(risk_result):
    """
    Determine the authentication flow based on the AI risk result.

    IMPORTANT:
    Trust score is NOT used here.

    AI risk is completely independent of trust score.
    """

    if risk_result["requires_step_up"]:

        return {
            "risk_level": "HIGH",
            "risk_score": risk_result["risk_score"],
            "additional_2fa_required": True,
            "phone_otp_required": True,
            "mentor_approval_required": True
        }

    return {
        "risk_level": "LOW",
        "risk_score": risk_result["risk_score"],
        "additional_2fa_required": False,
        "phone_otp_required": True,
        "mentor_approval_required": True
    }


# ============================================================
# RISK LEVEL
# ============================================================

def determine_risk_level(risk_score):
    """
    Convert the numerical risk score into a risk level.

    The trained model uses 50 as the step-up threshold.

    LOW:
        < 50

    HIGH:
        >= 50
    """

    if risk_score >= RISK_THRESHOLD:
        return "HIGH"

    return "LOW"


# ============================================================
# RISK FACTORS
# ============================================================

def determine_risk_factors(data):
    """
    Determine human-readable risk factors from security features.

    IMPORTANT:
    trust_score is intentionally NOT checked here.

    Risk factors are based only on the seven AI security features.
    """

    risk_factors = []


    # --------------------------------------------------------
    # Device
    # --------------------------------------------------------

    if data.get("known_device") == 0:
        risk_factors.append(
            "New device detected"
        )


    # --------------------------------------------------------
    # Location
    # --------------------------------------------------------

    if data.get("location_deviation", 0) > 0.6:
        risk_factors.append(
            "Unusual location deviation"
        )


    # --------------------------------------------------------
    # Failed login attempts
    # --------------------------------------------------------

    if data.get("failed_login_count", 0) > 2:
        risk_factors.append(
            "Multiple failed login attempts"
        )


    # --------------------------------------------------------
    # Password reset
    # --------------------------------------------------------

    if data.get("recent_password_reset") == 1:
        risk_factors.append(
            "Recent password reset"
        )


    # --------------------------------------------------------
    # MFA
    # --------------------------------------------------------

    if data.get("mfa_verified") == 0:
        risk_factors.append(
            "MFA not verified"
        )


    # --------------------------------------------------------
    # Phone change frequency
    # --------------------------------------------------------

    if data.get("phone_change_frequency", 0) > 2:
        risk_factors.append(
            "Frequent phone changes"
        )


    # --------------------------------------------------------
    # Login time
    # --------------------------------------------------------

    if data.get("login_time_deviation", 0) > 0.6:
        risk_factors.append(
            "Unusual login time pattern"
        )


    return risk_factors


# ============================================================
# HOME
# ============================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return jsonify({
        "status": "online",
        "service": "EduShield AI Risk Engine",
        "model_version": MODEL_VERSION,
        "risk_threshold": RISK_THRESHOLD,
        "trust_score_used_for_risk_prediction": False
    })


# ============================================================
# PREDICT RISK
# ============================================================

@app.route(
    "/predict-risk",
    methods=["POST"]
)
def predict():

    # --------------------------------------------------------
    # Get JSON request
    # --------------------------------------------------------

    data = request.get_json(
        silent=True
    )

    print(
        f"Received data: {data}"
    )


    # --------------------------------------------------------
    # Validate request body
    # --------------------------------------------------------

    if not data:

        return jsonify({
            "error": "Request body is required"
        }), 400


    if not isinstance(data, dict):

        return jsonify({
            "error": "Request body must be a JSON object"
        }), 400


    try:

        # ----------------------------------------------------
        # AI MODEL PREDICTION
        # ----------------------------------------------------

        risk_result = predict_risk(
            data
        )

        print(
            f"Risk result: {risk_result}"
        )


        # ----------------------------------------------------
        # Risk score
        # ----------------------------------------------------

        risk_score = float(
            risk_result["risk_score"]
        )


        # ----------------------------------------------------
        # Risk level
        # ----------------------------------------------------
        # Uses the same 50 threshold as the trained model.
        # ----------------------------------------------------

        risk_level = determine_risk_level(
            risk_score
        )


        # ----------------------------------------------------
        # Risk factors
        # ----------------------------------------------------

        risk_factors = determine_risk_factors(
            data
        )


        # ----------------------------------------------------
        # Authentication flow
        # ----------------------------------------------------

        authentication_flow = (
            determine_authentication_flow(
                {
                    "risk_score": risk_score,
                    "requires_step_up": (
                        risk_score >= RISK_THRESHOLD
                    )
                }
            )
        )


        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        return jsonify({

            "risk_score": round(
                risk_score,
                2
            ),

            "risk_level": risk_level,

            "risk_factors": risk_factors,

            "model_version": MODEL_VERSION,

            "requires_step_up": (
                risk_score >= RISK_THRESHOLD
            ),

            "authentication_flow": (
                authentication_flow
            )

        })


    except KeyError as e:

        print(
            f"Missing feature: {e}"
        )

        return jsonify({
            "error": f"Missing required feature: {str(e)}"
        }), 400


    except ValueError as e:

        print(
            f"Invalid input: {e}"
        )

        return jsonify({
            "error": str(e)
        }), 400


    except Exception as e:

        print(
            f"Error occurred: {e}"
        )

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# RUN AI API
# ============================================================

if __name__ == "__main__":

    print("\n" + "=" * 60)
    print("EDU-SHIELD AI RISK ENGINE")
    print("=" * 60)

    print(
        "Service: EduShield AI Risk Engine"
    )

    print(
        "Host: 127.0.0.1"
    )

    print(
        "Port: 5001"
    )

    print(
        "Risk Threshold:",
        RISK_THRESHOLD
    )

    print(
        "Trust Score Used:",
        "NO"
    )

    print("=" * 60 + "\n")


    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    ) 