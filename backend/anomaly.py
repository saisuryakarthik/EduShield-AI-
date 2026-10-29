"""
Anomaly indicators and security alerts.

The risk model answers "how likely is this request to be fraudulent?".
An anomaly *indicator* answers a narrower, auditable question: "which
concrete pieces of evidence are present?". The indicators are computed
from the same stored security context that the model scores, so the two
can never disagree about the underlying facts.

Alerts are the durable record of that evidence. One alert exists per
request: re-evaluating a request updates the open alert instead of
piling up duplicates, and resolving it records who acted and why.
"""

import json


SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

STATUS_OPEN = "open"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_RESOLVED = "resolved"


# ---------------------------------------------------------------
# Indicator definitions
# ---------------------------------------------------------------
#
# ``weight`` feeds the alert severity only. It is deliberately simple
# and reviewable: no weights are learned, and none of them touch the
# model's risk score.

INDICATORS = (
    {
        "code": "NEW_DEVICE",
        "label": "Unrecognised device",
        "weight": 2,
        "test": lambda f: int(f.get("known_device", 1)) == 0,
        "detail": (
            "The change was requested from a device that has not been "
            "seen for this account before."
        ),
    },
    {
        "code": "FAILED_LOGIN_BURST",
        "label": "Repeated failed sign-ins",
        "weight": 3,
        "test": lambda f: int(f.get("failed_login_count", 0)) >= 3,
        "detail": (
            "Several failed sign-in attempts were recorded before the "
            "request."
        ),
    },
    {
        "code": "RECENT_PASSWORD_RESET",
        "label": "Recent password reset",
        "weight": 2,
        "test": lambda f: int(f.get("recent_password_reset", 0)) == 1,
        "detail": (
            "The password was reset shortly before the request was made."
        ),
    },
    {
        "code": "MFA_NOT_VERIFIED",
        "label": "Multi-factor step not completed",
        "weight": 1,
        "test": lambda f: int(f.get("mfa_verified", 1)) == 0,
        "detail": (
            "The second authentication factor was not verified for this "
            "session."
        ),
    },
    {
        "code": "LOCATION_DEVIATION",
        "label": "Unusual location",
        "weight": 3,
        "test": lambda f: float(f.get("location_deviation", 0.0)) >= 0.6,
        "detail": (
            "The request originated from a location far from the "
            "account's usual activity."
        ),
    },
    {
        "code": "UNUSUAL_LOGIN_TIME",
        "label": "Unusual sign-in time",
        "weight": 1,
        "test": lambda f: float(f.get("login_time_deviation", 0.0)) >= 0.6,
        "detail": (
            "The activity happened at a time that is unusual for this "
            "account."
        ),
    },
    {
        "code": "REPEATED_PHONE_CHANGES",
        "label": "Repeated phone changes",
        "weight": 2,
        "test": lambda f: int(f.get("phone_change_frequency", 0)) >= 2,
        "detail": (
            "This account has changed its phone number several times "
            "recently."
        ),
    },
)


def evaluate(features):
    """
    Compute the indicators present in one security-context snapshot.

    Returns a dict with the triggered indicators (in stable order),
    their combined weight and an overall severity. A request with no
    triggered indicator is ``info`` severity with an empty list, which
    is a meaningful result rather than an error.
    """

    triggered = []

    for definition in INDICATORS:
        try:
            present = bool(definition["test"](features))
        except (TypeError, ValueError):
            present = False

        if not present:
            continue

        triggered.append({
            "code": definition["code"],
            "label": definition["label"],
            "weight": definition["weight"],
            "detail": definition["detail"],
        })

    score = sum(item["weight"] for item in triggered)

    if score >= 8:
        severity = SEVERITY_CRITICAL
    elif score >= 4:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_INFO

    return {
        "indicators": triggered,
        "count": len(triggered),
        "score": score,
        "severity": severity,
        "summary": summarise(triggered, severity),
    }


def summarise(indicators, severity):
    """One sentence a mentor can read without extra context."""

    if not indicators:
        return (
            "No anomaly indicators were present: the request matches "
            "this account's normal behaviour."
        )

    labels = ", ".join(item["label"].lower() for item in indicators)

    return (
        f"{len(indicators)} anomaly indicator(s) present "
        f"({labels}); overall severity is {severity}."
    )


# ---------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------

def upsert_alert(cursor, request_id, user_id, assessment,
                 alert_type="ANOMALY_INDICATORS", source="system",
                 raised_by=None):
    """
    Record the indicators for a request, one alert per request/type.

    An existing *open* alert is refreshed so a re-run never duplicates
    rows. Resolved alerts are left untouched: history is not rewritten.
    """

    indicators = assessment["indicators"]

    cursor.execute(
        """
        SELECT alert_id, status
        FROM security_alerts
        WHERE request_id = %s
          AND alert_type = %s
        ORDER BY alert_id DESC
        LIMIT 1
        """,
        (request_id, alert_type)
    )

    existing = cursor.fetchone()

    payload = json.dumps({
        "score": assessment["score"],
        "count": assessment["count"],
        "indicators": indicators,
    })

    if existing and existing["status"] != STATUS_RESOLVED:
        cursor.execute(
            """
            UPDATE security_alerts
            SET
                user_id = %s,
                severity = %s,
                message = %s,
                indicators_json = %s
            WHERE alert_id = %s
            """,
            (
                user_id,
                assessment["severity"],
                assessment["summary"][:500],
                payload,
                existing["alert_id"],
            )
        )

        return existing["alert_id"]

    cursor.execute(
        """
        INSERT INTO security_alerts
        (
            request_id, user_id, alert_type, severity, source,
            message, indicators_json, status, raised_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            request_id,
            user_id,
            alert_type,
            assessment["severity"],
            source,
            assessment["summary"][:500],
            payload,
            STATUS_OPEN,
            raised_by,
        )
    )

    return cursor.lastrowid


def list_alerts(cursor, status=None, severity=None, limit=100):
    """Alerts with the request and student they belong to."""

    cursor.execute(
        """
        SELECT
            a.alert_id,
            a.request_id,
            a.user_id,
            a.alert_type,
            a.severity,
            a.source,
            a.status,
            a.message,
            a.indicators_json,
            a.created_at,
            a.acknowledged_at,
            a.acknowledged_by,
            a.resolved_at,
            a.resolved_by,
            a.resolution_note,
            u.name AS student_name,
            u.email AS student_email,
            ai.risk_level,
            ai.risk_score,
            p.requested_at AS request_created_at
        FROM security_alerts a
        JOIN users u ON u.user_id = a.user_id
        LEFT JOIN phone_change_requests p
            ON p.request_id = a.request_id
        LEFT JOIN ai_assessments ai
            ON ai.request_id = a.request_id
        WHERE (%s IS NULL OR a.status = %s)
          AND (%s IS NULL OR a.severity = %s)
        ORDER BY
            FIELD(a.severity, 'critical', 'warning', 'info'),
            a.created_at DESC
        LIMIT %s
        """,
        (status, status, severity, severity, int(limit))
    )

    alerts = cursor.fetchall()

    for alert in alerts:
        value = alert.get("indicators_json")
        if isinstance(value, str):
            try:
                alert["indicators"] = json.loads(value)
            except json.JSONDecodeError:
                alert["indicators"] = {}
        elif value is None:
            alert["indicators"] = {}
        else:
            alert["indicators"] = value

    return alerts


def get_alert(cursor, alert_id):
    """One alert by id, or None."""

    cursor.execute(
        """
        SELECT
            a.*,
            u.name AS student_name,
            u.email AS student_email
        FROM security_alerts a
        JOIN users u ON u.user_id = a.user_id
        WHERE a.alert_id = %s
        """,
        (alert_id,)
    )

    alert = cursor.fetchone()

    if alert:
        value = alert.get("indicators_json")
        if isinstance(value, str):
            try:
                alert["indicators"] = json.loads(value)
            except json.JSONDecodeError:
                alert["indicators"] = {}
        elif value is None:
            alert["indicators"] = {}

    return alert


def acknowledge_alert(cursor, alert_id, actor_id):
    """Mark an open alert as seen by a mentor or admin."""

    cursor.execute(
        """
        UPDATE security_alerts
        SET
            status = %s,
            acknowledged_at = NOW(),
            acknowledged_by = %s
        WHERE alert_id = %s
          AND status = %s
        """,
        (STATUS_ACKNOWLEDGED, actor_id, alert_id, STATUS_OPEN)
    )

    return cursor.rowcount > 0


def resolve_alert(cursor, alert_id, actor_id, note=None):
    """Close an alert with a recorded reason."""

    cursor.execute(
        """
        UPDATE security_alerts
        SET
            status = %s,
            resolved_at = NOW(),
            resolved_by = %s,
            resolution_note = %s
        WHERE alert_id = %s
          AND status <> %s
        """,
        (STATUS_RESOLVED, actor_id, note, alert_id, STATUS_RESOLVED)
    )

    return cursor.rowcount > 0


def open_alert_count(cursor):
    """Counts per severity for the admin/mentor header."""

    cursor.execute(
        """
        SELECT severity, COUNT(*) AS total
        FROM security_alerts
        WHERE status <> %s
        GROUP BY severity
        """,
        (STATUS_RESOLVED,)
    )

    counts = {
        SEVERITY_CRITICAL: 0,
        SEVERITY_WARNING: 0,
        SEVERITY_INFO: 0,
    }

    for row in cursor.fetchall():
        counts[row["severity"]] = int(row["total"] or 0)

    return counts
