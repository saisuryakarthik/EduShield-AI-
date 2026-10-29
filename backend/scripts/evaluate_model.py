"""
Measure the persisted risk model and store the result.

This script is the *only* writer of ``model_evaluations`` rows. It:

1. loads the dataset with the same columns and the same group-aware
   split the trainer uses (``GroupShuffleSplit``, seed 42, 20% test);
2. loads the artifact that is actually deployed;
3. computes accuracy / precision / recall / F1 / ROC-AUC and a
   threshold sweep from that held-out split;
4. writes the numbers to the database.

It refuses to invent a metric: if the dataset or artifact is missing,
it stops with a clear error. ``--dry-run`` prints the result without
writing anything.

Usage (from ``backend``):

    python scripts/evaluate_model.py
    python scripts/evaluate_model.py --version risk-v1 --dry-run
"""

import argparse
import json
import os
import sys

import joblib
import mysql.connector
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import config  # noqa: E402
import model_registry  # noqa: E402

PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

DATASET_NAME = "edushield_phone_change_dataset.csv"
ARTIFACT_DIR = os.path.join(BACKEND_DIR, "ai", "artifacts")
DEFAULT_MODEL = os.path.join(ARTIFACT_DIR, "logistic_regression.pkl")
DEFAULT_FEATURES = os.path.join(ARTIFACT_DIR, "features.json")
DEFAULT_CONFIG = os.path.join(ARTIFACT_DIR, "config.json")

TARGET = "label"
GROUP = "user_id"
TEST_SIZE = 0.20
SPLIT_SEED = 42
THRESHOLDS = (40, 50, 60, 70, 80)


def find_dataset(explicit=None):
    if explicit:
        if not os.path.exists(explicit):
            raise FileNotFoundError(explicit)
        return explicit

    for root, _, files in os.walk(PROJECT_ROOT):
        if DATASET_NAME in files:
            return os.path.join(root, DATASET_NAME)

    raise FileNotFoundError(
        f"{DATASET_NAME} was not found under {PROJECT_ROOT}"
    )


def load_features(path=DEFAULT_FEATURES):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path=DEFAULT_CONFIG):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def split_dataset(frame, features):
    """
    Reproduce the trainer's split exactly.

    Returns (X_train, X_test, y_train, y_test, train_users, test_users).
    """

    missing = [
        column
        for column in features + [TARGET, GROUP]
        if column not in frame.columns
    ]

    if missing:
        raise ValueError(
            "Dataset is missing required columns: " + ", ".join(missing)
        )

    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=TEST_SIZE,
        random_state=SPLIT_SEED,
    )

    train_index, test_index = next(
        splitter.split(
            frame[features],
            frame[TARGET],
            groups=frame[GROUP],
        )
    )

    return (
        frame.iloc[train_index][features],
        frame.iloc[test_index][features],
        frame.iloc[train_index][TARGET],
        frame.iloc[test_index][TARGET],
        set(frame.iloc[train_index][GROUP]),
        set(frame.iloc[test_index][GROUP]),
    )


def threshold_analysis(y_true, probabilities):
    """Precision/recall at each operational risk threshold."""

    results = {}

    scores = probabilities * 100.0

    for threshold in THRESHOLDS:
        predicted = (scores >= threshold).astype(int)

        tn, fp, fn, tp = confusion_matrix(
            y_true, predicted, labels=[0, 1]
        ).ravel()

        results[str(threshold)] = {
            "require_step_up": int(tp + fp),
            "tp": int(tp),
            "fp": int(fp),
            "fn": int(fn),
            "tn": int(tn),
            "precision": round(
                float(tp / (tp + fp)) if (tp + fp) else 0.0, 4
            ),
            "recall": round(
                float(tp / (tp + fn)) if (tp + fn) else 0.0, 4
            ),
        }

    return results


def evaluate(dataset_path, model_path, features):
    frame = pd.read_csv(dataset_path)

    model = joblib.load(model_path)

    (
        X_train,
        X_test,
        y_train,
        y_test,
        train_users,
        test_users,
    ) = split_dataset(frame, features)

    probabilities = np.asarray(
        model.predict_proba(X_test)[:, 1]
    ).ravel()

    predicted = (probabilities >= 0.5).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_test, predicted, labels=[0, 1]
    ).ravel()

    metrics = {
        "accuracy": float(accuracy_score(y_test, predicted)),
        "precision": float(
            precision_score(y_test, predicted, zero_division=0)
        ),
        "recall": float(
            recall_score(y_test, predicted, zero_division=0)
        ),
        "f1": float(f1_score(y_test, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "test_samples": int(len(X_test)),
        "test_users": int(len(test_users)),
        "train_samples": int(len(X_train)),
        "train_users": int(len(train_users)),
        "user_overlap": int(len(train_users & test_users)),
    }

    confusion = {
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "positive_rate": round(float(y_test.mean()), 4),
    }

    return metrics, confusion, threshold_analysis(y_test, probabilities)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure the deployed risk model and store the result."
    )
    parser.add_argument("--dataset", help="Path to the labelled dataset")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--features", default=DEFAULT_FEATURES)
    parser.add_argument(
        "--version",
        help="Model version to attribute the result to "
             "(defaults to the active registry row)",
    )
    parser.add_argument("--dataset-name")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the result without writing to the database",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register the artifact as the active version before "
             "recording the evaluation",
    )

    args = parser.parse_args(argv)

    dataset_path = find_dataset(args.dataset)
    features = load_features(args.features)
    artifact_config = load_config()

    metrics, confusion, thresholds = evaluate(
        dataset_path, args.model, features
    )

    version = args.version

    connection = mysql.connector.connect(**config.DB_CONFIG)
    cursor = connection.cursor(dictionary=True)

    try:
        if version is None:
            active = model_registry.get_active_model(cursor)
            version = (
                active["model_version"] if active else None
            ) or "unregistered"

        if args.register:
            artifact_hash = model_registry.artifact_digest([
                args.model,
                args.features,
                DEFAULT_CONFIG,
            ])

            model_registry.register_model(
                cursor,
                model_version=version,
                model_type=artifact_config.get(
                    "model_type", "logistic_regression"
                ),
                artifact_hash=artifact_hash,
                features=features,
                risk_threshold=artifact_config.get("risk_threshold", 50),
                dataset_name=os.path.basename(dataset_path),
                notes="Registered by scripts/evaluate_model.py",
                activate=True,
            )

        dataset_name = (
            args.dataset_name or os.path.basename(dataset_path)
        )

        notes = (
            "Held-out split: GroupShuffleSplit(test_size=0.20, "
            f"random_state={SPLIT_SEED}) grouped by {GROUP}. "
            "Metrics are computed from the persisted artifact, not "
            "re-trained."
        )

        print(f"Dataset      : {dataset_path}")
        print(f"Artifact     : {args.model}")
        print(f"Version      : {version}")
        print(f"Samples      : train={metrics['train_samples']} "
              f"test={metrics['test_samples']}")
        print(f"Users        : train={metrics['train_users']} "
              f"test={metrics['test_users']} "
              f"overlap={metrics['user_overlap']}")
        print(f"Accuracy     : {metrics['accuracy']:.4f}")
        print(f"Precision    : {metrics['precision']:.4f}")
        print(f"Recall       : {metrics['recall']:.4f}")
        print(f"F1           : {metrics['f1']:.4f}")
        print(f"ROC-AUC      : {metrics['roc_auc']:.4f}")
        print(f"Confusion    : {confusion}")
        print("Thresholds   :")
        for threshold, stats in thresholds.items():
            print(
                f"  >= {threshold:>2}  step_up={stats['require_step_up']:>4}  "
                f"precision={stats['precision']:.4f}  "
                f"recall={stats['recall']:.4f}"
            )

        if args.dry_run:
            print("Dry run: nothing written.")
            return 0

        evaluation_id = model_registry.record_evaluation(
            cursor,
            model_version=version,
            dataset_name=dataset_name,
            metrics=metrics,
            confusion=confusion,
            threshold_analysis=thresholds,
            notes=notes,
        )

        connection.commit()

        print(f"Stored evaluation #{evaluation_id}.")

        return 0

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
