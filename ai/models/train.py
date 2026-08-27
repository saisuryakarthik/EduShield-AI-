import pandas as pd
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
import joblib
import json
import os
#Import metrics 
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    classification_report
)


#Random forest classifier
from sklearn.ensemble import RandomForestClassifier
# -----------------------------
# 1. LOAD DATA
# -----------------------------

edu = pd.read_csv("./EduShield-AI-/Dataset/edushield_phone_change_dataset.csv")
FEATURES = [
    "known_device",
    "location_deviation",
    "failed_login_count",
    "recent_password_reset",
    "mfa_verified",
    "phone_change_frequency",
    "login_time_deviation",
    "trust_score"
]

TARGET = "label"
GROUP = "user_id"

X = edu[FEATURES]
y = edu[TARGET]
groups = edu[GROUP]

# -----------------------------
# 2. USER-AWARE TRAIN/TEST SPLIT
# -----------------------------

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

# -----------------------------
# 3. VERIFY USER SEPARATION
# -----------------------------

train_users = set(groups.iloc[train_idx])
test_users = set(groups.iloc[test_idx])

print("TRAINING SET")
print("Samples:", len(X_train))
print("Users:", len(train_users))

print("\nTEST SET")
print("Samples:", len(X_test))
print("Users:", len(test_users))

print("\nUser overlap:")
print(len(train_users.intersection(test_users)))

# -----------------------------
# 4. PREPROCESSING + MODEL
# -----------------------------

model = Pipeline([
    ("scaler", StandardScaler()),
    ("classifier", LogisticRegression(
        max_iter=1000,
        random_state=42
    ))
])

# -----------------------------
# 5. TRAIN
# -----------------------------

model.fit(X_train, y_train)

print("\nModel training complete.")

# -----------------------------
# 6. PREDICTION
# -----------------------------

y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]

print("\nPredictions generated.")
print("Predictions:", len(y_pred))
print("Probabilities:", len(y_prob))

print("model evaluation")

# -----------------------------
# 7. MODEL EVALUATION
# -----------------------------

accuracy = accuracy_score(y_test, y_pred)
precision = precision_score(y_test, y_pred)
recall = recall_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)
roc_auc = roc_auc_score(y_test, y_prob)

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
print(classification_report(y_test, y_pred))

# -----------------------------
# 8. RANDOM FOREST
# -----------------------------

rf_model = RandomForestClassifier(
    n_estimators=200,
    random_state=42,
    n_jobs=-1
)

rf_model.fit(X_train, y_train)

print("\nRandom Forest training complete.")

# Predictions
rf_pred = rf_model.predict(X_test)
rf_prob = rf_model.predict_proba(X_test)[:, 1]

# -----------------------------
# 9. RANDOM FOREST EVALUATION
# -----------------------------

rf_accuracy = accuracy_score(y_test, rf_pred)
rf_precision = precision_score(y_test, rf_pred)
rf_recall = recall_score(y_test, rf_pred)
rf_f1 = f1_score(y_test, rf_pred)
rf_roc_auc = roc_auc_score(y_test, rf_prob)

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
print(classification_report(y_test, rf_pred))


# -----------------------------
# 10. RISK SCORE ANALYSIS
# -----------------------------


# Convert probability to 0-100 risk score
risk_scores = y_prob * 100

print("\nRISK SCORE ANALYSIS")
print("=" * 40)

print(f"Minimum Risk Score : {risk_scores.min():.2f}")
print(f"Maximum Risk Score : {risk_scores.max():.2f}")
print(f"Mean Risk Score    : {risk_scores.mean():.2f}")
print(f"Median Risk Score  : {np.median(risk_scores):.2f}")

# Risk score statistics by actual class
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
print(f"Legitimate : {legit_risk.mean():.2f}")
print(f"Suspicious : {suspicious_risk.mean():.2f}")

print("\nMedian Risk Score by Actual Class:")
print(f"Legitimate : {legit_risk.median():.2f}")
print(f"Suspicious : {suspicious_risk.median():.2f}")

# -----------------------------
# 11. RISK BAND ANALYSIS
# -----------------------------

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

# -----------------------------
# 12. STEP-UP AUTHENTICATION
#    THRESHOLD ANALYSIS
# -----------------------------



thresholds = [40, 50, 60, 70, 80]

print("\nSTEP-UP AUTHENTICATION THRESHOLD ANALYSIS")
print("=" * 60)

for threshold in thresholds:

    # Requests at or above threshold require extra 2FA
    step_up = (risk_scores >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_test,
        step_up
    ).ravel()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0

    print(f"\nThreshold: {threshold}")
    print(f"Require 2FA : {tp + fp}")
    print(f"TP          : {tp}")
    print(f"FP          : {fp}")
    print(f"FN          : {fn}")
    print(f"TN          : {tn}")
    print(f"Precision   : {precision:.4f}")
    print(f"Recall      : {recall:.4f}")

#Defining the threshold for step-up authentication based on the risk analysis
RISK_THRESHOLD = 50

requires_step_up = risk_scores >= RISK_THRESHOLD

print("Risk threshold:", RISK_THRESHOLD)
print("Requests requiring step-up authentication:",
      requires_step_up.sum())

# -----------------------------
# SAVE MODEL
# -----------------------------

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

MODEL_DIR = os.path.join(BASE_DIR, "artifacts")

os.makedirs(MODEL_DIR, exist_ok=True)

joblib.dump(model, os.path.join(MODEL_DIR, "logistic_regression.pkl"))

print("Model saved.")
# -----------------------------
# SAVE MODEL ARTIFACTS
# -----------------------------

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

MODEL_DIR = os.path.join(BASE_DIR, "artifacts")

os.makedirs(MODEL_DIR, exist_ok=True)

# Save complete ML pipeline
joblib.dump(
    model,
    os.path.join(MODEL_DIR, "logistic_regression.pkl")
)

print("Model pipeline saved.")

# Save feature list
with open(
    os.path.join(MODEL_DIR, "features.json"), "w"
) as f:
    json.dump(FEATURES, f, indent=4)

print("Features saved.")

# Save configuration
config = {
    "risk_threshold": 50,
    "risk_score_scale": "0-100",
    "model_type": "logistic_regression",
    "step_up_authentication": "IFHE_EMAIL_2FA"
}

with open(
    os.path.join(MODEL_DIR, "config.json"), "w"
) as f:
    json.dump(config, f, indent=4)

print("Configuration saved.")