import hashlib
import os
import json
import joblib
import pandas as pd


# ============================================================
# PATHS
# ============================================================

# Current file:
# backend/ai/models/predict.py
#
# BASE_DIR:
# backend/ai
#
# ARTIFACT_DIR:
# backend/ai/artifacts

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

ARTIFACT_DIR = os.path.join(
    BASE_DIR,
    "artifacts"
)


MODEL_PATH = os.path.join(
    ARTIFACT_DIR,
    "logistic_regression.pkl"
)

FEATURES_PATH = os.path.join(
    ARTIFACT_DIR,
    "features.json"
)

CONFIG_PATH = os.path.join(
    ARTIFACT_DIR,
    "config.json"
)


# ============================================================
# CHECK ARTIFACTS
# ============================================================

if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(
        f"ML model not found:\n{MODEL_PATH}\n\n"
        "Run train.py first."
    )

if not os.path.exists(FEATURES_PATH):
    raise FileNotFoundError(
        f"Feature configuration not found:\n{FEATURES_PATH}\n\n"
        "Run train.py first."
    )

if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(
        f"Model configuration not found:\n{CONFIG_PATH}\n\n"
        "Run train.py first."
    )


def file_sha256(path):
    """SHA-256 of an artifact file."""

    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)

    return digest.hexdigest()


def verify_artifact_integrity(path, expected_digest):
    """
    Refuse to load a model whose bytes do not match the pinned digest.

    The digest is optional for older artifacts, but when present it
    stops a replaced or corrupted .pkl from being executed by joblib.
    """

    if not expected_digest:
        return True

    actual_digest = file_sha256(path)

    if actual_digest != str(expected_digest).lower():
        raise ValueError(
            "Model artifact integrity check failed: "
            "logistic_regression.pkl does not match the digest in "
            "config.json. Re-deploy the trusted artifact or retrain."
        )

    return True


# ============================================================
# LOAD FEATURES
# ============================================================

with open(
    FEATURES_PATH,
    "r"
) as f:
    FEATURES = json.load(f)


# ============================================================
# LOAD CONFIGURATION
# ============================================================

with open(
    CONFIG_PATH,
    "r"
) as f:
    CONFIG = json.load(f)


MODEL_VERSION = CONFIG.get(
    "model_version",
    "logistic-regression-v1"
)


# ============================================================
# VERIFY AND LOAD TRAINED MODEL
# ============================================================

verify_artifact_integrity(
    MODEL_PATH,
    CONFIG.get("artifact_sha256")
)

model = joblib.load(
    MODEL_PATH
)


# ============================================================
# MODEL FEATURE VALIDATION
# ============================================================

EXPECTED_FEATURES = [
    "known_device",
    "location_deviation",
    "failed_login_count",
    "recent_password_reset",
    "mfa_verified",
    "phone_change_frequency",
    "login_time_deviation"
]


if FEATURES != EXPECTED_FEATURES:
    raise ValueError(
        "\nFeature mismatch detected.\n\n"
        f"Expected features:\n{EXPECTED_FEATURES}\n\n"
        f"Loaded features:\n{FEATURES}\n\n"
        "Run train.py again to regenerate the model artifacts."
    )


# ============================================================
# CONFIRM TRUST SCORE IS NOT USED
# ============================================================

if "trust_score" in FEATURES:
    raise ValueError(
        "ERROR: trust_score is present in the AI model features. "
        "Risk prediction must remain independent of trust_score."
    )


# ============================================================
# RISK PREDICTION
# ============================================================

def predict_risk(request_data):
    """
    Predict AI security risk for a phone-change request.

    IMPORTANT:
    trust_score is intentionally NOT used by this function.

    The AI risk model uses only:
        - known_device
        - location_deviation
        - failed_login_count
        - recent_password_reset
        - mfa_verified
        - phone_change_frequency
        - login_time_deviation
    """

    # --------------------------------------------------------
    # Validate request data
    # --------------------------------------------------------

    if not isinstance(request_data, dict):
        raise ValueError(
            "request_data must be a dictionary."
        )


    # --------------------------------------------------------
    # Check for missing features
    # --------------------------------------------------------

    missing_features = [
        feature
        for feature in FEATURES
        if feature not in request_data
    ]

    if missing_features:
        raise ValueError(
            "Missing required AI risk features: "
            + ", ".join(missing_features)
        )


    # --------------------------------------------------------
    # Build input dataframe
    # --------------------------------------------------------
    # The feature order is taken directly from features.json,
    # which was generated by train.py.
    #
    # trust_score is NOT included.
    # --------------------------------------------------------

    data = pd.DataFrame(
        [
            [
                request_data[feature]
                for feature in FEATURES
            ]
        ],
        columns=FEATURES
    )


    # --------------------------------------------------------
    # Ensure numeric values
    # --------------------------------------------------------

    try:
        data = data.astype(float)

    except (ValueError, TypeError) as e:
        raise ValueError(
            f"AI risk features must contain numeric values. "
            f"Details: {e}"
        )


    # --------------------------------------------------------
    # Predict suspicious probability
    # --------------------------------------------------------

    probability = model.predict_proba(
        data
    )[0][1]


    # --------------------------------------------------------
    # Convert probability to 0-100 risk score
    # --------------------------------------------------------

    risk_score = probability * 100


    # --------------------------------------------------------
    # Get configured threshold
    # --------------------------------------------------------

    risk_threshold = float(
        CONFIG.get(
            "risk_threshold",
            50
        )
    )


    # --------------------------------------------------------
    # Step-up authentication decision
    # --------------------------------------------------------

    requires_step_up = (
        risk_score >= risk_threshold
    )


    # --------------------------------------------------------
    # Risk level
    # --------------------------------------------------------
    # This matches the threshold used by train.py:
    #
    # < 50  = LOW
    # >= 50 = HIGH
    # --------------------------------------------------------

    if risk_score >= risk_threshold:
        risk_level = "HIGH"
    else:
        risk_level = "LOW"


    # --------------------------------------------------------
    # Return result
    # --------------------------------------------------------

    return {
        "risk_score": round(
            float(risk_score),
            2
        ),
        "risk_level": risk_level,
        "requires_step_up": bool(
            requires_step_up
        )
    }


# ============================================================
# MODEL INFORMATION
# ============================================================

def get_model_info():
    """
    Return information about the currently loaded model.
    """

    return {
        "model_type": CONFIG.get(
            "model_type",
            "logistic_regression"
        ),
        "model_version": MODEL_VERSION,
        "trained_sklearn_version": CONFIG.get(
            "trained_sklearn_version"
        ),
        "artifact_sha256": CONFIG.get(
            "artifact_sha256"
        ),
        "risk_threshold": CONFIG.get(
            "risk_threshold",
            50
        ),
        "risk_score_scale": CONFIG.get(
            "risk_score_scale",
            "0-100"
        ),
        "features": FEATURES,
        "trust_score_used_for_risk_prediction": False
    }


# ============================================================
# TEST PREDICTION
# ============================================================

if __name__ == "__main__":

    print("\nEDU-SHIELD AI RISK ENGINE")
    print("=" * 50)


    # --------------------------------------------------------
    # Display loaded model information
    # --------------------------------------------------------

    print("\nModel:")
    print(
        CONFIG.get(
            "model_type",
            "logistic_regression"
        )
    )


    print("\nRisk Threshold:")
    print(
        CONFIG.get(
            "risk_threshold",
            50
        )
    )


    print("\nFeatures:")
    for feature in FEATURES:
        print(f"  - {feature}")


    print("\nTrust Score Used:")
    print("NO")


    # --------------------------------------------------------
    # Test request
    # --------------------------------------------------------

    test_request = {
    "known_device": 0,
    "location_deviation": 1.0,
    "failed_login_count": 5,
    "recent_password_reset": 1,
    "mfa_verified": 0,
    "phone_change_frequency": 3,
    "login_time_deviation": 1.0
}


    # --------------------------------------------------------
    # Run prediction
    # --------------------------------------------------------

    try:

        result = predict_risk(
            test_request
        )


        print("\nTEST PREDICTION")
        print("=" * 50)

        print(
            "Risk Score:",
            result["risk_score"]
        )

        print(
            "Risk Level:",
            result["risk_level"]
        )

        print(
            "Step-up Authentication:",
            result["requires_step_up"]
        )


        print("\nPrediction completed successfully.")


    except Exception as e:

        print("\nPrediction failed.")
        print(
            "Error:",
            str(e)
        )
        
        
test_request = {
    "known_device": 0,
    "location_deviation": 1.0,
    "failed_login_count": 5,
    "recent_password_reset": 1,
    "mfa_verified": 0,
    "phone_change_frequency": 3,
    "login_time_deviation": 1.0
}