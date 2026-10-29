"""
Structured request timeline.

``request_timeline`` is an append-only, ordered account of everything
that happened to a request. It is written in the same transaction as
the change it describes, so the timeline is never a reconstruction
guess.

For requests created before this table existed, ``backfill`` derives
events from the durable records that already exist (the request row,
the AI assessment, mentor reviews, OTP state and audit logs). Derived
rows are tagged ``details_json.source = "backfill"`` so they are never
confused with events written live.
"""

import json


CATEGORY_SUBMITTED = "submitted"
CATEGORY_VERIFICATION = "verification"
CATEGORY_AI = "ai"
CATEGORY_ALERT = "alert"
CATEGORY_DECISION = "decision"
CATEGORY_NOTIFICATION = "notification"
CATEGORY_RECOVERY = "recovery"
CATEGORY_SYSTEM = "system"

ACTOR_STUDENT = "student"
ACTOR_MENTOR = "mentor"
ACTOR_ADMIN = "admin"
ACTOR_PARENT = "parent"
ACTOR_SYSTEM = "system"


def add_event(cursor, request_id, event_type, category, title,
              actor_type=ACTOR_SYSTEM, actor_id=None, summary=None,
              details=None):
    """
    Append one timeline event.

    ``details`` must never contain OTP codes, hashes or tokens; it is
    returned to API clients as-is.
    """

    cursor.execute(
        """
        INSERT INTO request_timeline
        (
            request_id, event_type, category, actor_type,
            actor_id, title, summary, details_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            request_id,
            event_type,
            category,
            actor_type,
            actor_id,
            title[:160],
            (summary or "")[:500] or None,
            json.dumps(details) if details is not None else None,
        )
    )

    return cursor.lastrowid


def list_events(cursor, request_id):
    """Timeline events for one request, oldest first."""

    cursor.execute(
        """
        SELECT
            timeline_id,
            request_id,
            event_type,
            category,
            actor_type,
            actor_id,
            title,
            summary,
            details_json,
            created_at
        FROM request_timeline
        WHERE request_id = %s
        ORDER BY created_at ASC, timeline_id ASC
        """,
        (request_id,)
    )

    events = cursor.fetchall()

    for event in events:
        value = event.get("details_json")

        if isinstance(value, str):
            try:
                event["details"] = json.loads(value)
            except json.JSONDecodeError:
                event["details"] = {}
        else:
            event["details"] = value or {}

    return events


def _event_exists(cursor, request_id, event_type, minute_key):
    """
    Cheap duplicate guard for backfill.

    ``minute_key`` is a stable string (usually the source timestamp
    truncated to the minute) stored in the event summary, so re-running
    the backfill cannot duplicate rows.
    """

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM request_timeline
        WHERE request_id = %s
          AND event_type = %s
          AND JSON_UNQUOTE(details_json -> '$.source_key') = %s
        """,
        (request_id, event_type, minute_key)
    )

    return int((cursor.fetchone() or {}).get("total") or 0) > 0


def backfill(cursor, request_id):
    """
    Derive timeline events from records that predate the timeline table.

    Safe to call repeatedly: every derived event carries a
    ``source_key`` and duplicates are skipped. Live events are never
    modified or removed.
    """

    cursor.execute(
        """
        SELECT
            request_id,
            user_id,
            old_phone,
            new_phone,
            requested_at,
            auth_status,
            parent_verification_status,
            parent_verified_at,
            status,
            mentor_id,
            reviewed_at,
            rejection_reason
        FROM phone_change_requests
        WHERE request_id = %s
        """,
        (request_id,)
    )

    req = cursor.fetchone()

    if not req:
        return 0

    created = 0

    def derived(event_type, category, title, actor_type, summary,
                details, source_key):
        nonlocal created

        if _event_exists(cursor, request_id, event_type, source_key):
            return

        payload = dict(details or {})
        payload["source"] = "backfill"
        payload["source_key"] = source_key

        add_event(
            cursor,
            request_id,
            event_type,
            category,
            title,
            actor_type=actor_type,
            actor_id=None,
            summary=summary,
            details=payload,
        )

        created += 1

    requested_key = str(req["requested_at"] or "")

    derived(
        "REQUEST_SUBMITTED",
        CATEGORY_SUBMITTED,
        "Phone change requested",
        ACTOR_STUDENT,
        f"{req['old_phone']} -> {req['new_phone']}",
        {"old_phone": req["old_phone"], "new_phone": req["new_phone"]},
        requested_key,
    )

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

    assessment = cursor.fetchone()

    if assessment:
        derived(
            "AI_ASSESSED",
            CATEGORY_AI,
            f"AI risk assessed: {assessment['risk_level']}",
            ACTOR_SYSTEM,
            f"Risk score {assessment['risk_score']:.2f}",
            {
                "risk_score": assessment["risk_score"],
                "risk_level": assessment["risk_level"],
                "model_version": assessment["model_version"],
            },
            str(assessment["assessed_at"] or ""),
        )

    cursor.execute(
        """
        SELECT
            channel,
            verified,
            verified_at,
            attempts
        FROM phone_change_otps
        WHERE request_id = %s
        ORDER BY channel
        """,
        (request_id,)
    )

    for otp in cursor.fetchall():
        if not otp["verified"]:
            continue

        derived(
            f"{otp['channel']}_VERIFIED",
            CATEGORY_VERIFICATION,
            f"{otp['channel']} verification completed",
            ACTOR_SYSTEM,
            "One-time code verified.",
            {
                "channel": otp["channel"],
                "attempts": otp["attempts"],
            },
            f"{otp['channel']}:{otp['verified_at'] or ''}",
        )

    if req["parent_verification_status"] == "VERIFIED":
        derived(
            "PARENT_VERIFIED",
            CATEGORY_VERIFICATION,
            "Parent verification completed",
            ACTOR_PARENT,
            "Both parent channels were verified.",
            {"status": "VERIFIED"},
            str(req["parent_verified_at"] or ""),
        )

    cursor.execute(
        """
        SELECT review_id, mentor_id, decision, reason, reviewed_at
        FROM mentor_reviews
        WHERE request_id = %s
        """,
        (request_id,)
    )

    for review in cursor.fetchall():
        derived(
            "MENTOR_DECISION",
            CATEGORY_DECISION,
            f"Mentor {review['decision'].lower()} the request",
            ACTOR_MENTOR,
            review["reason"],
            {
                "decision": review["decision"],
                "mentor_id": review["mentor_id"],
            },
            str(review["reviewed_at"] or ""),
        )

    cursor.execute(
        """
        SELECT log_id, actor, action, details, timestamp
        FROM audit_logs
        WHERE request_id = %s
        ORDER BY timestamp ASC, log_id ASC
        """,
        (request_id,)
    )

    for log in cursor.fetchall():
        value = log["details"]

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {}

        derived(
            f"AUDIT_{log['action']}",
            CATEGORY_SYSTEM,
            f"Audit: {log['action']}",
            ACTOR_SYSTEM,
            None,
            {"audit": value, "actor": log["actor"]},
            f"{log['log_id']}",
        )

    return created
