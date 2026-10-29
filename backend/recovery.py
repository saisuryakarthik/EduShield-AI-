"""
Controlled emergency account recovery.

Recovery is deliberately *not* a self-service password reset. A
password reset by e-mail alone is exactly the attack a phone-change
fraudster wants. Instead:

1. An **admin** opens a recovery for a locked-out account and records a
   reason. This is the authorization step.
2. The account holder proves identity with a single-use code sent to
   their **registered** e-mail (and, when configured, their registered
   phone). The code is stored only as a keyed hash.
3. Only after a successful verification may the password be replaced.

Every transition is written to ``audit_logs`` by the API layer, and
``account_recoveries`` is the durable record of what happened. Attempts
are capped, the record expires and it can be revoked at any time.
"""

import hashlib
import hmac
import secrets

import otp as otp_module


RECOVERY_CODE_LENGTH = 8

STATUS_PENDING = "pending"
STATUS_VERIFIED = "verified"
STATUS_COMPLETED = "completed"
STATUS_EXPIRED = "expired"
STATUS_REVOKED = "revoked"
STATUS_FAILED = "failed"


def generate_recovery_code():
    """Return a cryptographically random numeric code."""

    value = secrets.randbelow(10 ** RECOVERY_CODE_LENGTH)

    return str(value).zfill(RECOVERY_CODE_LENGTH)


def hash_recovery_code(recovery_id, code):
    """
    Keyed hash of a code, bound to the recovery record.

    Uses the same server-side pepper as the OTPs so a database leak
    alone cannot be brute-forced offline.
    """

    message = f"recovery:{int(recovery_id)}:{code}".encode("utf-8")

    return hmac.new(
        otp_module.get_otp_pepper(),
        message,
        hashlib.sha256
    ).hexdigest()


def code_matches(recovery_id, code, stored_hash):
    """Constant-time comparison against the stored hash."""

    if not stored_hash:
        return False

    return hmac.compare_digest(
        hash_recovery_code(recovery_id, code),
        stored_hash
    )


# ---------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------

def start_recovery(cursor, user_id, requested_by, reason,
                   ttl_minutes=30, max_attempts=3):
    """
    Open a recovery and return ``(recovery_id, code, expires_at)``.

    The plaintext code is returned exactly once, to the caller, so it
    can be delivered out-of-band. It is never stored or logged.
    """

    cursor.execute(
        """
        SELECT user_id, account_status
        FROM users
        WHERE user_id = %s
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        raise ValueError("User not found")

    if user["account_status"] == "active":
        raise ValueError(
            "Account is already active; use the normal change flow"
        )

    cursor.execute(
        """
        SELECT recovery_id
        FROM account_recoveries
        WHERE user_id = %s
          AND status IN ('pending', 'verified')
        """,
        (user_id,)
    )

    if cursor.fetchone():
        raise ValueError(
            "A recovery is already in progress for this account"
        )

    ttl_minutes = max(5, min(int(ttl_minutes or 30), 1440))
    max_attempts = max(1, min(int(max_attempts or 3), 10))

    cursor.execute(
        """
        INSERT INTO account_recoveries
        (
            user_id, requested_by, reason, status,
            attempts, max_attempts, expires_at
        )
        VALUES (%s, %s, %s, %s, 0, %s,
                DATE_ADD(NOW(), INTERVAL %s MINUTE))
        """,
        (
            user_id,
            requested_by,
            reason,
            STATUS_PENDING,
            max_attempts,
            ttl_minutes,
        )
    )

    recovery_id = cursor.lastrowid

    code = generate_recovery_code()

    cursor.execute(
        """
        UPDATE account_recoveries
        SET code_hash = %s
        WHERE recovery_id = %s
        """,
        (hash_recovery_code(recovery_id, code), recovery_id)
    )

    return recovery_id, code


def get_recovery(cursor, recovery_id):
    """One recovery record, or None."""

    cursor.execute(
        """
        SELECT
            r.*,
            u.name AS user_name,
            u.email AS user_email,
            u.phone_number AS user_phone,
            u.account_status AS user_account_status,
            a.name AS requested_by_name
        FROM account_recoveries r
        JOIN users u ON u.user_id = r.user_id
        JOIN users a ON a.user_id = r.requested_by
        WHERE r.recovery_id = %s
        """,
        (recovery_id,)
    )

    return cursor.fetchone()


def verify_code(cursor, recovery_id, code):
    """
    Check a recovery code and record the attempt.

    Returns a dict describing the outcome; it never raises for a wrong
    code, because callers need to distinguish "wrong", "locked",
    "expired" and "verified" without inspecting database rows.
    """

    recovery = get_recovery(cursor, recovery_id)

    if not recovery:
        return {"ok": False, "reason": "not_found"}

    status = recovery["status"]

    if status in (STATUS_COMPLETED, STATUS_REVOKED, STATUS_EXPIRED,
                  STATUS_FAILED):
        return {"ok": False, "reason": status}

    if status == STATUS_VERIFIED:
        return {"ok": True, "reason": "already_verified"}

    cursor.execute(
        """
        SELECT (expires_at < NOW()) AS expired,
               locked,
               attempts,
               max_attempts
        FROM account_recoveries
        WHERE recovery_id = %s
        """,
        (recovery_id,)
    )

    state = cursor.fetchone()

    if state["expired"]:
        cursor.execute(
            """
            UPDATE account_recoveries
            SET status = %s
            WHERE recovery_id = %s
            """,
            (STATUS_EXPIRED, recovery_id)
        )
        return {"ok": False, "reason": "expired"}

    if state["locked"]:
        return {"ok": False, "reason": "locked"}

    if not code_matches(
        recovery_id, str(code or "").strip(), recovery["code_hash"]
    ):
        attempts = int(state["attempts"] or 0) + 1
        locked = attempts >= int(state["max_attempts"] or 3)

        cursor.execute(
            """
            UPDATE account_recoveries
            SET attempts = %s,
                locked = %s,
                status = %s
            WHERE recovery_id = %s
            """,
            (
                attempts,
                1 if locked else 0,
                STATUS_FAILED if locked else STATUS_PENDING,
                recovery_id,
            )
        )

        return {
            "ok": False,
            "reason": "locked" if locked else "invalid_code",
            "attempts_left": max(
                0, int(state["max_attempts"] or 3) - attempts
            ),
        }

    cursor.execute(
        """
        UPDATE account_recoveries
        SET status = %s,
            verified_at = NOW(),
            code_hash = NULL
        WHERE recovery_id = %s
        """,
        (STATUS_VERIFIED, recovery_id)
    )

    return {"ok": True, "reason": "verified"}


def complete(cursor, recovery_id, password_hash, actor_id=None):
    """
    Finish a verified recovery: reactivate the account and set the new
    password.

    The password hash must already be produced by ``auth.hash_password``;
    this module never sees plaintext passwords.
    """

    cursor.execute(
        """
        SELECT user_id, status
        FROM account_recoveries
        WHERE recovery_id = %s
        """,
        (recovery_id,)
    )

    recovery = cursor.fetchone()

    if not recovery:
        return {"ok": False, "reason": "not_found"}

    if recovery["status"] != STATUS_VERIFIED:
        return {"ok": False, "reason": recovery["status"]}

    cursor.execute(
        """
        UPDATE users
        SET password_hash = %s,
            account_status = 'active'
        WHERE user_id = %s
        """,
        (password_hash, recovery["user_id"])
    )

    cursor.execute(
        """
        UPDATE account_recoveries
        SET status = %s,
            completed_at = NOW()
        WHERE recovery_id = %s
        """,
        (STATUS_COMPLETED, recovery_id)
    )

    return {
        "ok": True,
        "reason": "completed",
        "user_id": recovery["user_id"],
        "completed_by": actor_id,
    }


def revoke(cursor, recovery_id, actor_id=None):
    """Cancel a pending or verified recovery."""

    cursor.execute(
        """
        UPDATE account_recoveries
        SET status = %s
        WHERE recovery_id = %s
          AND status IN ('pending', 'verified')
        """,
        (STATUS_REVOKED, recovery_id)
    )

    return cursor.rowcount > 0


def expire_stale(cursor):
    """Mark overdue pending recoveries as expired. Returns the count."""

    cursor.execute(
        """
        UPDATE account_recoveries
        SET status = %s
        WHERE status IN ('pending', 'verified')
          AND expires_at < NOW()
        """,
        (STATUS_EXPIRED,)
    )

    return cursor.rowcount


def list_recoveries(cursor, status=None, limit=100):
    """Recent recovery records for the admin panel."""

    cursor.execute(
        """
        SELECT
            r.recovery_id,
            r.user_id,
            u.name AS user_name,
            u.email AS user_email,
            r.requested_by,
            a.name AS requested_by_name,
            r.reason,
            r.status,
            r.attempts,
            r.max_attempts,
            r.locked,
            r.created_at,
            r.expires_at,
            r.verified_at,
            r.completed_at
        FROM account_recoveries r
        JOIN users u ON u.user_id = r.user_id
        JOIN users a ON a.user_id = r.requested_by
        WHERE (%s IS NULL OR r.status = %s)
        ORDER BY r.created_at DESC, r.recovery_id DESC
        LIMIT %s
        """,
        (status, status, int(limit))
    )

    return cursor.fetchall()
