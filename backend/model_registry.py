"""
Model versioning and monitoring.

A trained artifact is not just a file: it is a *version* that can be
promoted, retired and compared. This module owns that lifecycle.

Three tables back it (migration 005):

``model_registry``
    One row per trained artifact. Exactly one row is ``active`` at a
    time; promoting a version retires the previous one.

``model_evaluations``
    Measured evaluation results. Rows are written by
    ``backend/scripts/evaluate_model.py`` from a real group-aware split
    of the dataset. The dashboard reads these rows; it never invents a
    metric.

``model_predictions``
    One row per scored request: which version produced the score, how
    long it took and the exact feature vector that was fed in. This is
    what makes an assessment explainable after the fact and what the
    monitoring snapshot is computed from.

The functions here take a cursor so they run inside the caller's
transaction: a rolled-back request must not leave a prediction record
behind.
"""

import hashlib
import json
import os


# ---------------------------------------------------------------
# Artifact identity
# ---------------------------------------------------------------

def artifact_digest(paths):
    """
    SHA-256 over one or more artifact files.

    The digest is what ties a registry row to the bytes that were
    actually loaded, so a swapped artifact cannot masquerade as the
    registered version.
    """

    if isinstance(paths, str):
        paths = [paths]

    digest = hashlib.sha256()

    for path in sorted(paths):
        digest.update(os.path.basename(path).encode("utf-8"))

        if not os.path.exists(path):
            digest.update(b"<missing>")
            continue

        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)

    return digest.hexdigest()


# ---------------------------------------------------------------
# Registry
# ---------------------------------------------------------------

def register_model(cursor, model_version, model_type, artifact_hash=None,
                   features=None, risk_threshold=50, dataset_name=None,
                   trained_at=None, notes=None, activate=True):
    """
    Insert or update one model version.

    Re-registering the same version updates its metadata instead of
    creating a duplicate, so the registry is safe to run repeatedly.
    When ``activate`` is true every other version is retired first, so
    exactly one version is active.
    """

    cursor.execute(
        """
        SELECT model_id
        FROM model_registry
        WHERE model_version = %s
        """,
        (model_version,)
    )

    row = cursor.fetchone()

    feature_list = json.dumps(list(features or []))

    if row:
        cursor.execute(
            """
            UPDATE model_registry
            SET
                model_type = %s,
                artifact_hash = %s,
                feature_list = %s,
                risk_threshold = %s,
                dataset_name = %s,
                trained_at = %s,
                notes = %s
            WHERE model_version = %s
            """,
            (
                model_type,
                artifact_hash,
                feature_list,
                float(risk_threshold),
                dataset_name,
                trained_at,
                notes,
                model_version,
            )
        )

        model_id = row["model_id"]

    else:
        cursor.execute(
            """
            INSERT INTO model_registry
            (
                model_version, model_type, artifact_hash, feature_list,
                risk_threshold, dataset_name, trained_at, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                model_version,
                model_type,
                artifact_hash,
                feature_list,
                float(risk_threshold),
                dataset_name,
                trained_at,
                notes,
            )
        )

        model_id = cursor.lastrowid

    if activate:
        activate_model(cursor, model_version)

    return model_id


def activate_model(cursor, model_version):
    """Make one version active and retire the others."""

    cursor.execute(
        """
        UPDATE model_registry
        SET status = 'retired'
        WHERE status = 'active'
          AND model_version <> %s
        """,
        (model_version,)
    )

    cursor.execute(
        """
        UPDATE model_registry
        SET status = 'active'
        WHERE model_version = %s
        """,
        (model_version,)
    )


def list_models(cursor):
    """Every registered version, newest registration first."""

    cursor.execute(
        """
        SELECT
            model_id,
            model_version,
            model_type,
            status,
            artifact_hash,
            feature_list,
            risk_threshold,
            dataset_name,
            trained_at,
            registered_at,
            notes
        FROM model_registry
        ORDER BY registered_at DESC, model_id DESC
        """
    )

    models = cursor.fetchall()

    for model in models:
        if isinstance(model.get("feature_list"), str):
            try:
                model["feature_list"] = json.loads(
                    model["feature_list"]
                )
            except json.JSONDecodeError:
                model["feature_list"] = []

    return models


def get_active_model(cursor):
    """The version currently in service, or None."""

    cursor.execute(
        """
        SELECT
            model_id,
            model_version,
            model_type,
            status,
            artifact_hash,
            feature_list,
            risk_threshold,
            dataset_name,
            trained_at,
            registered_at
        FROM model_registry
        WHERE status = 'active'
        ORDER BY registered_at DESC
        LIMIT 1
        """
    )

    model = cursor.fetchone()

    if model and isinstance(model.get("feature_list"), str):
        try:
            model["feature_list"] = json.loads(model["feature_list"])
        except json.JSONDecodeError:
            model["feature_list"] = []

    return model


# ---------------------------------------------------------------
# Predictions (monitoring)
# ---------------------------------------------------------------

def record_prediction(cursor, request_id, user_id, model_version,
                      risk_score, risk_level, latency_ms=0.0,
                      feature_values=None):
    """
    Store one scored prediction.

    Re-scoring the same request overwrites the previous record instead
    of duplicating it, so the monitoring tables stay one row per
    request.
    """

    cursor.execute(
        """
        INSERT INTO model_predictions
        (
            request_id, user_id, model_version, risk_score,
            risk_level, latency_ms, feature_values
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            user_id = VALUES(user_id),
            model_version = VALUES(model_version),
            risk_score = VALUES(risk_score),
            risk_level = VALUES(risk_level),
            latency_ms = VALUES(latency_ms),
            feature_values = VALUES(feature_values),
            predicted_at = NOW()
        """,
        (
            request_id,
            user_id,
            model_version,
            float(risk_score),
            risk_level,
            float(latency_ms or 0.0),
            json.dumps(feature_values or {}),
        )
    )


def get_prediction(cursor, request_id):
    """
    The stored prediction for a request, with its feature snapshot.

    This is the *actual* input the model was given, which is what the
    explanation is computed from.
    """

    cursor.execute(
        """
        SELECT
            prediction_id,
            request_id,
            user_id,
            model_version,
            risk_score,
            risk_level,
            latency_ms,
            feature_values,
            predicted_at
        FROM model_predictions
        WHERE request_id = %s
        """,
        (request_id,)
    )

    row = cursor.fetchone()

    if row and isinstance(row.get("feature_values"), str):
        try:
            row["feature_values"] = json.loads(row["feature_values"])
        except json.JSONDecodeError:
            row["feature_values"] = {}

    return row


def background_samples(cursor, limit=50, exclude_request_id=None):
    """
    Real historical feature vectors, newest first.

    Used by the permutation-importance explanation. These are the
    feature vectors that were actually scored, not synthetic data.
    """

    cursor.execute(
        """
        SELECT request_id, feature_values
        FROM model_predictions
        WHERE feature_values IS NOT NULL
          AND JSON_LENGTH(feature_values) > 0
          AND (%s IS NULL OR request_id <> %s)
        ORDER BY predicted_at DESC
        LIMIT %s
        """,
        (exclude_request_id, exclude_request_id, int(limit))
    )

    samples = []

    for row in cursor.fetchall():
        values = row.get("feature_values")

        if isinstance(values, str):
            try:
                values = json.loads(values)
            except json.JSONDecodeError:
                continue

        if isinstance(values, dict) and values:
            samples.append(values)

    return samples


def monitoring_snapshot(cursor, model_version=None, days=30):
    """
    Real operational numbers for the monitoring dashboard.

    Every number is computed from stored predictions. When there are no
    predictions the counters are zero and ``available`` is False, so
    the UI can say "no data yet" instead of showing a fake chart.
    """

    cursor.execute(
        """
        SELECT COUNT(*) AS predictions,
               COUNT(DISTINCT model_version) AS versions,
               AVG(risk_score) AS avg_risk,
               MIN(risk_score) AS min_risk,
               MAX(risk_score) AS max_risk,
               AVG(latency_ms) AS avg_latency,
               MAX(latency_ms) AS max_latency,
               SUM(
                   CASE WHEN risk_level = 'HIGH' THEN 1 ELSE 0 END
               ) AS high_risk_count,
               SUM(
                   CASE WHEN risk_level = 'LOW' THEN 1 ELSE 0 END
               ) AS low_risk_count
        FROM model_predictions
        WHERE predicted_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
          AND (%s IS NULL OR model_version = %s)
        """,
        (int(days), model_version, model_version)
    )

    totals = cursor.fetchone() or {}

    predictions = int(totals.get("predictions") or 0)

    cursor.execute(
        """
        SELECT
            model_version,
            COUNT(*) AS predictions,
            AVG(risk_score) AS avg_risk,
            AVG(latency_ms) AS avg_latency,
            MAX(latency_ms) AS max_latency,
            SUM(
                CASE WHEN risk_level = 'HIGH' THEN 1 ELSE 0 END
            ) AS high_risk_count
        FROM model_predictions
        WHERE predicted_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        GROUP BY model_version
        ORDER BY predictions DESC
        """,
        (int(days),)
    )

    per_version = cursor.fetchall()

    cursor.execute(
        """
        SELECT risk_level, COUNT(*) AS total
        FROM model_predictions
        WHERE predicted_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
          AND (%s IS NULL OR model_version = %s)
        GROUP BY risk_level
        """,
        (int(days), model_version, model_version)
    )

    distribution = {
        row["risk_level"]: int(row["total"] or 0)
        for row in cursor.fetchall()
    }

    # Requests that were scored but have no prediction record show up
    # as a monitoring gap rather than being silently ignored.
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM phone_change_requests p
        LEFT JOIN model_predictions m
            ON m.request_id = p.request_id
        WHERE p.status IN ('APPROVED', 'REJECTED')
          AND m.prediction_id IS NULL
        """)
    unscored = int(
        (cursor.fetchone() or {}).get("total") or 0
    )

    latencies = [
        float(row["avg_latency"] or 0.0) for row in per_version
    ]

    return {
        "available": predictions > 0,
        "window_days": int(days),
        "model_version": model_version,
        "predictions": predictions,
        "versions_in_use": int(totals.get("versions") or 0),
        "average_risk_score": (
            round(float(totals["avg_risk"]), 2)
            if totals.get("avg_risk") is not None else None
        ),
        "min_risk_score": (
            round(float(totals["min_risk"]), 2)
            if totals.get("min_risk") is not None else None
        ),
        "max_risk_score": (
            round(float(totals["max_risk"]), 2)
            if totals.get("max_risk") is not None else None
        ),
        "average_latency_ms": (
            round(float(totals["avg_latency"]), 2)
            if totals.get("avg_latency") is not None else None
        ),
        "max_latency_ms": (
            round(float(totals["max_latency"]), 2)
            if totals.get("max_latency") is not None else None
        ),
        "high_risk_predictions": int(totals.get("high_risk_count") or 0),
        "low_risk_predictions": int(totals.get("low_risk_count") or 0),
        "risk_level_distribution": distribution,
        "per_version": per_version,
        "requests_without_prediction": unscored,
    }


# ---------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------

def record_evaluation(cursor, model_version, dataset_name, metrics,
                      confusion=None, threshold_analysis=None,
                      notes=None):
    """
    Store one measured evaluation result.

    ``metrics`` is a dict with the measured numbers. Only the keys the
    caller actually measured are stored; missing ones default to 0 and
    are flagged by ``notes``.
    """

    def number(key):
        value = metrics.get(key)
        return float(value) if value is not None else 0.0

    def integer(key):
        value = metrics.get(key)
        return int(value) if value is not None else 0

    cursor.execute(
        """
        INSERT INTO model_evaluations
        (
            model_version, dataset_name, test_samples, test_users,
            train_samples, train_users, user_overlap,
            accuracy, precision_score, recall_score, f1, roc_auc,
            confusion_json, threshold_json, notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            model_version,
            dataset_name,
            integer("test_samples"),
            integer("test_users"),
            integer("train_samples"),
            integer("train_users"),
            integer("user_overlap"),
            number("accuracy"),
            number("precision"),
            number("recall"),
            number("f1"),
            number("roc_auc"),
            json.dumps(confusion or {}),
            json.dumps(threshold_analysis or {}),
            notes,
        )
    )

    return cursor.lastrowid


def list_evaluations(cursor, model_version=None, limit=20):
    """Measured evaluation results, newest first."""

    cursor.execute(
        """
        SELECT
            evaluation_id,
            model_version,
            dataset_name,
            evaluated_at,
            test_samples,
            test_users,
            train_samples,
            train_users,
            user_overlap,
            accuracy,
            precision_score,
            recall_score,
            f1,
            roc_auc,
            confusion_json,
            threshold_json,
            notes
        FROM model_evaluations
        WHERE (%s IS NULL OR model_version = %s)
        ORDER BY evaluated_at DESC, evaluation_id DESC
        LIMIT %s
        """,
        (model_version, model_version, int(limit))
    )

    evaluations = cursor.fetchall()

    for evaluation in evaluations:
        for key in ("confusion_json", "threshold_json"):
            value = evaluation.get(key)
            if isinstance(value, str):
                try:
                    evaluation[key[:-5]] = json.loads(value)
                except json.JSONDecodeError:
                    evaluation[key[:-5]] = {}
            elif value is None:
                evaluation[key[:-5]] = {}

    return evaluations
