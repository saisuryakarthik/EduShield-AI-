import os
import json
import joblib
import pandas as pd


# -----------------------------
# LOAD MODEL ARTIFACTS
# -----------------------------

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

ARTIFACT_DIR = os.path.join(
    BASE_DIR,
    "artifacts"
)

# Load complete ML pipeline
model = joblib.load(
    os.path.join(
        ARTIFACT_DIR,
        "logistic_regression.pkl"
    )
)

# Load feature configuration
with open(
    os.path.join(
        ARTIFACT_DIR,
        "features.json"
    )
) as f:
    FEATURES = json.load(f)

# Load system configuration
with open(
    os.path.join(
        ARTIFACT_DIR,
        "config.json"
    )
) as f:
    CONFIG = json.load(f)


# -----------------------------
# RISK PREDICTION
# -----------------------------

def predict_risk(request_data):

    # Create dataframe in the exact
    # feature order used during training
    data = pd.DataFrame(
        [[request_data[feature] for feature in FEATURES]],
        columns=FEATURES
    )

    # Get probability of suspicious class
    probability = model.predict_proba(data)[0][1]

    # Convert probability to 0-100
    risk_score = probability * 100

    # Check threshold
    requires_step_up = (
        risk_score >= CONFIG["risk_threshold"]
    )

    # Determine risk level
    if risk_score >= CONFIG["risk_threshold"]:
        risk_level = "HIGH"
    else:
        risk_level = "LOW"

    return {
        "risk_score": round(float(risk_score), 2),
        "risk_level": risk_level,
        "requires_step_up": bool(requires_step_up)
    }


# -----------------------------
# TEST PREDICTION
# -----------------------------

if __name__ == "__main__":

    test_request = {
        "known_device": 0,
        "location_deviation": 0.72,
        "failed_login_count": 3,
        "recent_password_reset": 1,
        "mfa_verified": 1,
        "phone_change_frequency": 2,
        "login_time_deviation": 0.61,
        "trust_score": 35
    }

    result = predict_risk(test_request)

    print("\nEDU-SHIELD RISK PREDICTION")
    print("=" * 40)

    print("Risk Score:", result["risk_score"])
    print("Risk Level:", result["risk_level"])
    print(
        "Step-up Authentication:",
        result["requires_step_up"]
    )