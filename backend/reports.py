"""
Authorized security report exports (CSV and PDF).

Every row in a report comes from the database. Nothing is estimated,
sampled or hard-coded. The caller is responsible for authorization:
these helpers do not decide who may read what, they only assemble the
data and serialize it.

CSV uses ``\\r\\n`` line endings and quotes every field, which is what
spreadsheet tools expect. PDF rendering is delegated to
``backend/pdfwriter.py`` so no native PDF dependency is required.
"""

import csv
import io
import json

import anomaly
import pdfwriter
import timeline


ALERT_COLUMNS = [
    ("alert_id", "Alert ID"),
    ("created_at", "Raised at"),
    ("severity", "Severity"),
    ("status", "Status"),
    ("alert_type", "Type"),
    ("student_name", "Student"),
    ("student_email", "Student email"),
    ("request_id", "Request"),
    ("risk_level", "AI risk level"),
    ("risk_score", "AI risk score"),
    ("message", "Summary"),
    ("acknowledged_by", "Acknowledged by"),
    ("acknowledged_at", "Acknowledged at"),
    ("resolved_by", "Resolved by"),
    ("resolved_at", "Resolved at"),
    ("resolution_note", "Resolution note"),
]

REQUEST_COLUMNS = [
    ("request_id", "Request"),
    ("student_name", "Student"),
    ("student_email", "Student email"),
    ("old_phone", "Old phone"),
    ("new_phone", "New phone"),
    ("status", "Status"),
    ("requested_at", "Requested at"),
    ("risk_level", "AI risk level"),
    ("risk_score", "AI risk score"),
    ("indicator_count", "Anomaly indicators"),
    ("alert_severity", "Alert severity"),
    ("mentor_name", "Mentor"),
    ("reviewed_at", "Reviewed at"),
    ("rejection_reason", "Rejection reason"),
]

AUDIT_COLUMNS = [
    ("log_id", "Log ID"),
    ("timestamp", "Timestamp"),
    ("request_id", "Request"),
    ("user_id", "User"),
    ("actor", "Actor"),
    ("action", "Action"),
    ("details", "Details"),
]


# ---------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------

def _clean(value):
    """Render a database value for CSV output."""

    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)

    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")

    return str(value)


def fetch_alerts(cursor, since_days=90, severity=None, status=None,
                 limit=2000):
    """Alert rows joined with student, request and AI assessment."""

    cursor.execute(
        """
        SELECT
            a.alert_id,
            a.created_at,
            a.severity,
            a.status,
            a.alert_type,
            u.name AS student_name,
            u.email AS student_email,
            a.request_id,
            ai.risk_level,
            ai.risk_score,
            a.message,
            a.acknowledged_by,
            a.acknowledged_at,
            a.resolved_by,
            a.resolved_at,
            a.resolution_note
        FROM security_alerts a
        JOIN users u ON u.user_id = a.user_id
        LEFT JOIN ai_assessments ai
            ON ai.request_id = a.request_id
        WHERE a.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
          AND (%s IS NULL OR a.severity = %s)
          AND (%s IS NULL OR a.status = %s)
        ORDER BY a.created_at DESC, a.alert_id DESC
        LIMIT %s
        """,
        (
            int(since_days),
            severity, severity,
            status, status,
            int(limit),
        )
    )

    return cursor.fetchall()


def fetch_requests(cursor, since_days=90, status=None, limit=2000):
    """Request rows with assessment, indicator and mentor context."""

    cursor.execute(
        """
        SELECT
            p.request_id,
            u.name AS student_name,
            u.email AS student_email,
            p.old_phone,
            p.new_phone,
            p.status,
            p.requested_at,
            ai.risk_level,
            ai.risk_score,
            m.name AS mentor_name,
            p.reviewed_at,
            p.rejection_reason,
            (
                SELECT COUNT(*)
                FROM security_alerts a
                WHERE a.request_id = p.request_id
                  AND a.status <> 'resolved'
            ) AS indicator_count,
            (
                SELECT a.severity
                FROM security_alerts a
                WHERE a.request_id = p.request_id
                ORDER BY FIELD(a.severity, 'critical', 'warning', 'info')
                LIMIT 1
            ) AS alert_severity
        FROM phone_change_requests p
        JOIN users u ON u.user_id = p.user_id
        LEFT JOIN ai_assessments ai
            ON ai.request_id = p.request_id
        LEFT JOIN users m
            ON m.user_id = p.mentor_id
        WHERE p.requested_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
          AND (%s IS NULL OR p.status = %s)
        ORDER BY p.requested_at DESC
        LIMIT %s
        """,
        (int(since_days), status, status, int(limit))
    )

    return cursor.fetchall()


def fetch_audit(cursor, request_id=None, since_days=90, limit=5000):
    """Structured audit log rows."""

    cursor.execute(
        """
        SELECT
            log_id,
            `timestamp`,
            request_id,
            user_id,
            actor,
            action,
            details
        FROM audit_logs
        WHERE `timestamp` >= DATE_SUB(NOW(), INTERVAL %s DAY)
          AND (%s IS NULL OR request_id = %s)
        ORDER BY `timestamp` DESC, log_id DESC
        LIMIT %s
        """,
        (int(since_days), request_id, request_id, int(limit))
    )

    return cursor.fetchall()


def fetch_request_report(cursor, request_id):
    """
    Everything needed for a single-request export.

    Returns None when the request does not exist.
    """

    cursor.execute(
        """
        SELECT
            p.request_id,
            p.user_id,
            p.old_phone,
            p.new_phone,
            p.requested_at,
            p.auth_status,
            p.parent_verification_status,
            p.parent_verified_at,
            p.status,
            p.mentor_id,
            p.reviewed_at,
            p.rejection_reason,
            u.name AS student_name,
            u.email AS student_email,
            u.institutional_email,
            u.department,
            u.section,
            u.year,
            m.name AS mentor_name,
            m.email AS mentor_email
        FROM phone_change_requests p
        JOIN users u ON u.user_id = p.user_id
        LEFT JOIN users m ON m.user_id = p.mentor_id
        WHERE p.request_id = %s
        """,
        (request_id,)
    )

    request_row = cursor.fetchone()

    if not request_row:
        return None

    cursor.execute(
        """
        SELECT
            known_device,
            location_deviation,
            failed_login_count,
            recent_password_reset,
            mfa_verified,
            phone_change_frequency,
            login_time_deviation,
            trust_score,
            captured_at
        FROM security_context
        WHERE request_id = %s
        """,
        (request_id,)
    )

    security_context = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            risk_score,
            risk_level,
            risk_factors,
            model_version,
            assessed_at
        FROM ai_assessments
        WHERE request_id = %s
        """,
        (request_id,)
    )

    ai_assessment = cursor.fetchone()

    if ai_assessment and isinstance(ai_assessment["risk_factors"], str):
        try:
            ai_assessment["risk_factors"] = json.loads(
                ai_assessment["risk_factors"]
            )
        except json.JSONDecodeError:
            ai_assessment["risk_factors"] = []

    cursor.execute(
        """
        SELECT
            alert_id,
            severity,
            status,
            alert_type,
            message,
            created_at,
            resolution_note
        FROM security_alerts
        WHERE request_id = %s
        ORDER BY created_at ASC, alert_id ASC
        """,
        (request_id,)
    )

    alerts = cursor.fetchall()

    cursor.execute(
        """
        SELECT
            channel,
            verified,
            verified_at,
            attempts,
            locked
        FROM phone_change_otps
        WHERE request_id = %s
        ORDER BY channel
        """,
        (request_id,)
    )

    otp_channels = cursor.fetchall()

    timeline.backfill(cursor, request_id)
    events = timeline.list_events(cursor, request_id)

    assessment = (
        anomaly.evaluate(security_context)
        if security_context
        else None
    )

    return {
        "request": request_row,
        "security_context": security_context,
        "ai_assessment": ai_assessment,
        "alerts": alerts,
        "otp_channels": otp_channels,
        "timeline": events,
        "indicators": assessment,
    }


# ---------------------------------------------------------------
# CSV
# ---------------------------------------------------------------

def to_csv(rows, columns):
    """Serialize rows to CSV using ``columns`` = [(key, header), ...]."""

    buffer = io.StringIO(newline="")

    writer = csv.writer(
        buffer,
        quoting=csv.QUOTE_ALL,
        lineterminator="\r\n"
    )

    writer.writerow([header for _, header in columns])

    for row in rows:
        writer.writerow([
            _clean(row.get(key)) for key, _ in columns
        ])

    return buffer.getvalue()


# ---------------------------------------------------------------
# PDF
# ---------------------------------------------------------------

def _format_value(value):
    if value is None:
        return "—"

    if isinstance(value, float):
        return f"{value:.2f}"

    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)

    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")

    return str(value)


def alerts_pdf(rows, since_days=90, severity=None, status=None):
    """PDF export of the alert table."""

    blocks = [
        (
            "paragraph",
            f"Alerts from the last {int(since_days)} days. "
            f"Severity filter: {severity or 'all'}. "
            f"Status filter: {status or 'all'}. "
            f"{len(rows)} row(s)."
        ),
        ("space", 6),
    ]

    if not rows:
        blocks.append(("paragraph", "No alerts matched this filter."))
    else:
        table_rows = [
            [
                row["created_at"],
                row["severity"],
                row["status"],
                row["student_name"],
                row["request_id"] or "—",
                row["risk_level"] or "—",
                row["message"],
            ]
            for row in rows
        ]

        blocks.append((
            "table",
            [
                "Raised",
                "Severity",
                "Status",
                "Student",
                "Request",
                "AI risk",
                "Summary",
            ],
            table_rows,
            [0.14, 0.10, 0.11, 0.17, 0.13, 0.08, 0.27],
        ))

    return pdfwriter.render("Security alerts report", blocks)


def requests_pdf(rows, since_days=90, status=None):
    """PDF export of the request table."""

    blocks = [
        (
            "paragraph",
            f"Requests from the last {int(since_days)} days. "
            f"Status filter: {status or 'all'}. "
            f"{len(rows)} row(s)."
        ),
        ("space", 6),
    ]

    if not rows:
        blocks.append(("paragraph", "No requests matched this filter."))
    else:
        table_rows = [
            [
                row["requested_at"],
                row["student_name"],
                row["request_id"],
                row["status"],
                row["risk_level"] or "—",
                (
                    f"{row['risk_score']:.1f}"
                    if row["risk_score"] is not None else "—"
                ),
                str(row["indicator_count"] or 0),
                row["mentor_name"] or "—",
            ]
            for row in rows
        ]

        blocks.append((
            "table",
            [
                "Requested",
                "Student",
                "Request",
                "Status",
                "AI risk",
                "Score",
                "Indicators",
                "Mentor",
            ],
            table_rows,
            [0.14, 0.17, 0.13, 0.13, 0.10, 0.08, 0.10, 0.15],
        ))

    return pdfwriter.render("Security requests report", blocks)


def request_pdf(report):
    """Full single-request PDF: facts, AI, indicators, timeline."""

    request_row = report["request"]
    context = report["security_context"] or {}
    assessment = report["ai_assessment"] or {}
    indicators = report["indicators"] or {}

    blocks = [
        (
            "paragraph",
            f"Request {request_row['request_id']} — "
            f"{request_row['student_name']} "
            f"({request_row['student_email']})"
        ),
        ("space", 4),
        ("subheading", "Request facts"),
        ("kv", "Old phone", request_row["old_phone"]),
        ("kv", "New phone", request_row["new_phone"]),
        ("kv", "Status", request_row["status"]),
        ("kv", "Requested at", _format_value(request_row["requested_at"])),
        ("kv", "Auth status", request_row["auth_status"]),
        (
            "kv",
            "Parent verification",
            request_row["parent_verification_status"],
        ),
        ("kv", "Mentor", request_row["mentor_name"] or "Unassigned"),
        ("kv", "Reviewed at", _format_value(request_row["reviewed_at"])),
        (
            "kv",
            "Rejection reason",
            request_row["rejection_reason"] or "—",
        ),
        ("subheading", "Security context"),
    ]

    if context:
        for key, label in (
            ("known_device", "Known device"),
            ("location_deviation", "Location deviation"),
            ("failed_login_count", "Failed sign-ins"),
            ("recent_password_reset", "Recent password reset"),
            ("mfa_verified", "MFA verified"),
            ("phone_change_frequency", "Phone changes"),
            ("login_time_deviation", "Login time deviation"),
            ("trust_score", "Trust score (not a model input)"),
        ):
            blocks.append(("kv", label, _format_value(context.get(key))))
    else:
        blocks.append(("paragraph", "No security context was captured."))

    blocks.append(("subheading", "AI assessment"))

    if assessment:
        blocks.append(("kv", "Risk level", assessment["risk_level"]))
        blocks.append((
            "kv",
            "Risk score",
            f"{float(assessment['risk_score']):.2f}",
        ))
        blocks.append((
            "kv",
            "Model version",
            assessment["model_version"] or "unknown",
        ))
        blocks.append((
            "kv",
            "Assessed at",
            _format_value(assessment["assessed_at"]),
        ))
    else:
        blocks.append(("paragraph", "No AI assessment was recorded."))

    blocks.append(("subheading", "Anomaly indicators"))

    if indicators and indicators["indicators"]:
        blocks.append((
            "table",
            ["Indicator", "Weight", "Detail"],
            [
                [
                    item["label"],
                    str(item["weight"]),
                    item["detail"],
                ]
                for item in indicators["indicators"]
            ],
            [0.24, 0.08, 0.68],
        ))
        blocks.append((
            "paragraph",
            f"Overall severity: {indicators['severity']} "
            f"(weighted score {indicators['score']})."
        ))
    else:
        blocks.append((
            "paragraph",
            "No anomaly indicators were present.",
        ))

    blocks.append(("subheading", "Alerts"))

    if report["alerts"]:
        blocks.append((
            "table",
            ["Raised", "Severity", "Status", "Summary"],
            [
                [
                    _format_value(alert["created_at"]),
                    alert["severity"],
                    alert["status"],
                    alert["message"],
                ]
                for alert in report["alerts"]
            ],
            [0.20, 0.11, 0.13, 0.56],
        ))
    else:
        blocks.append(("paragraph", "No alerts were raised for this request."))

    blocks.append(("subheading", "Verification channels"))

    if report["otp_channels"]:
        blocks.append((
            "table",
            ["Channel", "Verified", "Attempts", "Locked"],
            [
                [
                    row["channel"],
                    "yes" if row["verified"] else "no",
                    str(row["attempts"]),
                    "yes" if row["locked"] else "no",
                ]
                for row in report["otp_channels"]
            ],
            [0.30, 0.25, 0.25, 0.20],
        ))
    else:
        blocks.append(("paragraph", "No verification channels were issued."))

    blocks.append(("subheading", "Timeline"))

    if report["timeline"]:
        blocks.append((
            "table",
            ["When", "Category", "Event", "Actor"],
            [
                [
                    _format_value(event["created_at"]),
                    event["category"],
                    event["title"],
                    event["actor_type"],
                ]
                for event in report["timeline"]
            ],
            [0.22, 0.16, 0.46, 0.16],
        ))
    else:
        blocks.append(("paragraph", "The timeline is empty."))

    blocks.append(("space", 10))
    blocks.append((
        "paragraph",
        "Generated by EduShield AI from stored records. This report "
        "contains personal data; share it only with authorized staff.",
    ))

    return pdfwriter.render(
        f"Security report — {request_row['request_id']}",
        blocks
    )
