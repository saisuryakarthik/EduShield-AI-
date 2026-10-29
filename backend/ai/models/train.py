import hashlib
import pandas as pd
import numpy as np
from pathlib import Path

import sklearn

from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    classification_report
)
from sklearn.ensemble import RandomForestClassifier

import joblib
import json


# ============================================================
# DATASET
# ============================================================

# Project root:
# C:\Users\Surya\Downloads\special project\special project
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATASET_NAME = "edushield_phone_change_dataset.csv"

# Automatically find the dataset anywhere inside the project
DATASET_PATH = next(
    PROJECT_ROOT.rglob(DATASET_NAME),
    None
)

if DATASET_PATH is None:
    raise FileNotFoundError(
        f"\nDataset '{DATASET_NAME}' was not found.\n"
        f"Searched inside:\n{PROJECT_ROOT}\n"
        f"\nMake sure the CSV exists inside the project folder."
    )

print("Dataset path:")
print(DATASET_PATH)

edu = pd.read_csv(DATASET_PATH)

print("\nDataset loaded successfully.")
print("Rows:", len(edu))
print("Columns:", len(edu.columns))


# ============================================================
# FEATURES
# ============================================================
# IMPORTANT:
# trust_score is intentionally NOT included.
#
# Risk prediction must be independent of the trust score.
# Trust score is calculated separately by the main backend.
# ============================================================

FEATURES = [
    "known_device",
    "location_deviation",
    "failed_login_count",
    "recent_password_reset",
    "mfa_verified",
    "phone_change_frequency",
    "login_time_deviation"
]

TARGET = "label"
GROUP = "user_id"


# ============================================================
# VALIDATE REQUIRED COLUMNS
# ============================================================

required_columns = FEATURES + [TARGET, GROUP]

missing_columns = [
    column
    for column in required_columns
    if column not in edu.columns
]

if missing_columns:
    raise ValueError(
        "\nMissing required columns:\n"
        + "\n".join(f"- {column}" for column in missing_columns)
    )

print("\nRequired columns validated successfully.")


# ============================================================
# DATA PREPARATION
# ============================================================

X = edu[FEATURES]
y = edu[TARGET]
groups = edu[GROUP]


print("\nFEATURES USED BY AI MODEL")
print("=" * 40)

for feature in FEATURES:
    print("-", feature)

print("\nTrust score included in model:")
print("NO")


# ============================================================
# TRAIN / TEST SPLIT
# ============================================================
# GroupShuffleSplit prevents the same user from appearing
# in both training and testing datasets.
# ============================================================

splitter = GroupShuffleSplit(
    n_splits=1,
    test_size=0.20,
    random_state=42
)

train_idx, test_idx = next(
    splitter.split(X, y, groups=groups)
)

X_train = X.iloc[train_idx]
X_test = X.iloc[test_idx]

y_train = y.iloc[train_idx]
y_test = y.iloc[test_idx]

train_users = set(groups.iloc[train_idx])
test_users = set(groups.iloc[test_idx])


print("\nTRAINING SET")
print("=" * 40)
print("Samples:", len(X_train))
print("Users:", len(train_users))

print("\nTEST SET")
print("=" * 40)
print("Samples:", len(X_test))
print("Users:", len(test_users))

print("\nUser overlap:")
print(len(train_users.intersection(test_users)))


# ============================================================
# LOGISTIC REGRESSION
# ============================================================

model = Pipeline([
    ("scaler", StandardScaler()),
    ("classifier", LogisticRegression(
        max_iter=1000,
        random_state=42
    ))
])


print("\nTRAINING LOGISTIC REGRESSION...")
print("=" * 40)

model.fit(X_train, y_train)

print("Model training complete.")


# ============================================================
# LOGISTIC REGRESSION PREDICTIONS
# ============================================================

y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]

print("\nPredictions generated.")
print("Predictions:", len(y_pred))
print("Probabilities:", len(y_prob))


# ============================================================
# LOGISTIC REGRESSION EVALUATION
# ============================================================

accuracy = accuracy_score(y_test, y_pred)

precision = precision_score(
    y_test,
    y_pred,
    zero_division=0
)

recall = recall_score(
    y_test,
    y_pred,
    zero_division=0
)

f1 = f1_score(
    y_test,
    y_pred,
    zero_division=0
)

roc_auc = roc_auc_score(
    y_test,
    y_prob
)


print("\nMODEL PERFORMANCE")
print("=" * 40)

print(f"Accuracy : {accuracy:.4f}")
print(f"Precision: {precision:.4f}")
print(f"Recall   : {recall:.4f}")
print(f"F1 Score : {f1:.4f}")
print(f"ROC-AUC  : {roc_auc:.4f}")


print("\nConfusion Matrix:")
print(confusion_matrix(y_test, y_pred))


print("\nClassification Report:")
print(
    classification_report(
        y_test,
        y_pred,
        zero_division=0
    )
)


# ============================================================
# RANDOM FOREST
# ============================================================

rf_model = RandomForestClassifier(
    n_estimators=200,
    random_state=42,
    n_jobs=-1
)


print("\nTRAINING RANDOM FOREST...")
print("=" * 40)

rf_model.fit(X_train, y_train)

print("Random Forest training complete.")


# ============================================================
# RANDOM FOREST PREDICTIONS
# ============================================================

rf_pred = rf_model.predict(X_test)
rf_prob = rf_model.predict_proba(X_test)[:, 1]


# ============================================================
# RANDOM FOREST EVALUATION
# ============================================================

rf_accuracy = accuracy_score(
    y_test,
    rf_pred
)

rf_precision = precision_score(
    y_test,
    rf_pred,
    zero_division=0
)

rf_recall = recall_score(
    y_test,
    rf_pred,
    zero_division=0
)

rf_f1 = f1_score(
    y_test,
    rf_pred,
    zero_division=0
)

rf_roc_auc = roc_auc_score(
    y_test,
    rf_prob
)


print("\nRANDOM FOREST PERFORMANCE")
print("=" * 40)

print(f"Accuracy : {rf_accuracy:.4f}")
print(f"Precision: {rf_precision:.4f}")
print(f"Recall   : {rf_recall:.4f}")
print(f"F1 Score : {rf_f1:.4f}")
print(f"ROC-AUC  : {rf_roc_auc:.4f}")


print("\nConfusion Matrix:")
print(confusion_matrix(y_test, rf_pred))


print("\nClassification Report:")
print(
    classification_report(
        y_test,
        rf_pred,
        zero_division=0
    )
)


# ============================================================
# RISK SCORE ANALYSIS
# ============================================================
# Logistic regression probability is converted to 0-100.
# ============================================================

risk_scores = y_prob * 100


print("\nRISK SCORE ANALYSIS")
print("=" * 40)

print(
    f"Minimum Risk Score : {risk_scores.min():.2f}"
)

print(
    f"Maximum Risk Score : {risk_scores.max():.2f}"
)

print(
    f"Mean Risk Score    : {risk_scores.mean():.2f}"
)

print(
    f"Median Risk Score  : {np.median(risk_scores):.2f}"
)


# ============================================================
# RISK SCORE BY ACTUAL CLASS
# ============================================================

risk_analysis = pd.DataFrame({
    "risk_score": risk_scores,
    "actual_label": y_test.values
})


legit_risk = risk_analysis[
    risk_analysis["actual_label"] == 0
]["risk_score"]


suspicious_risk = risk_analysis[
    risk_analysis["actual_label"] == 1
]["risk_score"]


print("\nAverage Risk Score by Actual Class:")

if len(legit_risk) > 0:
    print(
        f"Legitimate : {legit_risk.mean():.2f}"
    )
else:
    print("Legitimate : N/A")


if len(suspicious_risk) > 0:
    print(
        f"Suspicious : {suspicious_risk.mean():.2f}"
    )
else:
    print("Suspicious : N/A")


print("\nMedian Risk Score by Actual Class:")

if len(legit_risk) > 0:
    print(
        f"Legitimate : {legit_risk.median():.2f}"
    )
else:
    print("Legitimate : N/A")


if len(suspicious_risk) > 0:
    print(
        f"Suspicious : {suspicious_risk.median():.2f}"
    )
else:
    print("Suspicious : N/A")


# ============================================================
# RISK BAND ANALYSIS
# ============================================================

bins = [0, 20, 40, 60, 80, 100]

labels = [
    "0-20",
    "21-40",
    "41-60",
    "61-80",
    "81-100"
]


risk_analysis["risk_band"] = pd.cut(
    risk_analysis["risk_score"],
    bins=bins,
    labels=labels,
    include_lowest=True
)


print("\nRISK SCORE DISTRIBUTION")
print("=" * 40)

print(
    risk_analysis["risk_band"]
    .value_counts()
    .sort_index()
)


print("\nRISK BAND VS ACTUAL CLASS")
print("=" * 40)

print(
    pd.crosstab(
        risk_analysis["risk_band"],
        risk_analysis["actual_label"]
    )
)


# ============================================================
# STEP-UP AUTHENTICATION THRESHOLD ANALYSIS
# ============================================================

thresholds = [
    40,
    50,
    60,
    70,
    80
]


print("\nSTEP-UP AUTHENTICATION THRESHOLD ANALYSIS")
print("=" * 60)


for threshold in thresholds:

    step_up = (
        risk_scores >= threshold
    ).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_test,
        step_up,
        labels=[0, 1]
    ).ravel()

    threshold_precision = (
        tp / (tp + fp)
        if (tp + fp) > 0
        else 0
    )

    threshold_recall = (
        tp / (tp + fn)
        if (tp + fn) > 0
        else 0
    )

    print(f"\nThreshold: {threshold}")

    print(
        f"Require 2FA : {tp + fp}"
    )

    print(
        f"TP          : {tp}"
    )

    print(
        f"FP          : {fp}"
    )

    print(
        f"FN          : {fn}"
    )

    print(
        f"TN          : {tn}"
    )

    print(
        f"Precision   : {threshold_precision:.4f}"
    )

    print(
        f"Recall      : {threshold_recall:.4f}"
    )


# ============================================================
# FINAL RISK THRESHOLD
# ============================================================

RISK_THRESHOLD = 50

requires_step_up = (
    risk_scores >= RISK_THRESHOLD
)


print("\nFINAL RISK CONFIGURATION")
print("=" * 40)

print(
    "Risk threshold:",
    RISK_THRESHOLD
)

print(
    "Requests requiring step-up authentication:",
    requires_step_up.sum()
)


# ============================================================
# SAVE MODEL ARTIFACTS
# ============================================================

MODEL_DIR = PROJECT_ROOT / "backend" / "ai" / "artifacts"

MODEL_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ------------------------------------------------------------
# Save Logistic Regression model
# ------------------------------------------------------------

model_path = (
    MODEL_DIR /
    "logistic_regression.pkl"
)

joblib.dump(
    model,
    model_path
)

print("\nModel saved:")
print(model_path)


# ------------------------------------------------------------
# Save feature list
# ------------------------------------------------------------

features_path = (
    MODEL_DIR /
    "features.json"
)


with open(
    features_path,
    "w"
) as f:

    json.dump(
        FEATURES,
        f,
        indent=4
    )


print("Features saved:")
print(features_path)


# ------------------------------------------------------------
# Save configuration
# ------------------------------------------------------------

config = {
    "risk_threshold": RISK_THRESHOLD,
    "risk_score_scale": "0-100",
    "model_type": "logistic_regression",
    "step_up_authentication": "IFHE_EMAIL_2FA",
    "trust_score_used_for_risk_prediction": False,
    "model_version": "logistic-regression-v1",
    "trained_sklearn_version": sklearn.__version__,
    "artifact_sha256": hashlib.sha256(
        model_path.read_bytes()
    ).hexdigest()
}


config_path = (
    MODEL_DIR /
    "config.json"
)


with open(
    config_path,
    "w"
) as f:

    json.dump(
        config,
        f,
        indent=4
    )


print("Configuration saved:")
print(config_path)


# ============================================================
# FINAL VERIFICATION
# ============================================================

print("\n" + "=" * 60)
print("EDUSHIELD AI TRAINING COMPLETE")
print("=" * 60)

print("\nModel features:")

for feature in FEATURES:
    print(f"  ✓ {feature}")

print("\nTrust score:")
print("  ✗ NOT USED BY AI RISK MODEL")

print("\nArtifacts:")
print(f"  ✓ {model_path}")
print(f"  ✓ {features_path}")
print(f"  ✓ {config_path}")

print("\nRisk threshold:")
print(f"  {RISK_THRESHOLD}")

print("\nTraining completed successfully.")