"""
Persistent JWT revocation store.

Revoked tokens are recorded in the database instead of an in-process
set, so a revoked token stays revoked:

    * across an application restart (the store is not in memory),
    * across the workers of a multi-process server (gunicorn),
    * for every process that reads the same database.

Only the token identifier (jti), the owning user id, the revocation
time, the token's own expiry and an optional reason are stored. No
token, password, hash or other secret is ever written to this table.
"""

import datetime
import logging

import mysql.connector

from config import DB_CONFIG


logger = logging.getLogger("edushield.revocation")


class RevocationUnavailable(RuntimeError):
    """
    Raised when the revocation store cannot be read or written.

    The caller must treat this as "the token state is unknown" and fail
    closed: an unverifiable token is never accepted.
    """


# The application registers its own get_db() so this store always talks
# to the same database as the rest of the app. It is a callable, not a
# connection, so a test that patches the application's get_db() is
# honoured here too.
_connection_factory = None


def set_connection_factory(factory):
    """Register the connection factory used by this module."""

    global _connection_factory
    _connection_factory = factory


def get_db():
    """Open a connection to the revocation store."""

    if _connection_factory is not None:
        return _connection_factory()

    return mysql.connector.connect(**DB_CONFIG)


def _close(cursor, connection):
    try:
        if cursor:
            cursor.close()
    finally:
        if connection:
            connection.close()


def normalise_expiry(expires_at):
    """
    Convert a token expiry into a naive UTC datetime.

    Accepts a datetime (naive or aware) or a POSIX timestamp. The
    result is always a naive UTC datetime.
    """

    if expires_at is None:
        return None

    if isinstance(expires_at, datetime.datetime):
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(
                datetime.timezone.utc
            ).replace(tzinfo=None)

        return expires_at

    if isinstance(expires_at, (int, float)):
        return datetime.datetime.fromtimestamp(
            float(expires_at), datetime.timezone.utc
        ).replace(tzinfo=None)

    return None


def revoke(jti, user_id, expires_at, reason=None):
    """
    Record a revoked token.

    Idempotent: revoking the same jti twice updates the existing row
    instead of creating a second one. The first revocation time is kept
    because that is when the token actually died.
    """

    if not jti or not user_id:
        return False

    expiry = normalise_expiry(expires_at)

    if expiry is None:
        return False

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT revocation_id
            FROM revoked_tokens
            WHERE jti = %s
            """,
            (jti,)
        )

        if cursor.fetchone():
            cursor.execute(
                """
                UPDATE revoked_tokens
                SET reason = %s
                WHERE jti = %s
                """,
                (reason, jti)
            )
        else:
            # The token expiry arrives in UTC (that is what the `exp`
            # claim is). Every other timestamp in this database is
            # server local time, so the value is converted by the
            # server itself. The conversion uses the session's own
            # offset, so it is always right.
            cursor.execute(
                """
                INSERT INTO revoked_tokens
                (
                    jti,
                    user_id,
                    revoked_at,
                    expires_at,
                    reason
                )
                VALUES
                (
                    %s,
                    %s,
                    NOW(),
                    TIMESTAMPADD(
                        SECOND,
                        TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW()),
                        %s
                    ),
                    %s
                )
                """,
                (jti, user_id, expiry, reason)
            )

        connection.commit()

        return True

    except mysql.connector.Error as error:
        logger.error(
            "Could not persist token revocation (run migration 006): %s",
            error
        )
        raise RevocationUnavailable(str(error)) from error

    finally:
        _close(cursor, connection)


def is_revoked(jti):
    """
    True when the token identifier has been revoked.

    Raises RevocationUnavailable when the store cannot be read, so the
    caller fails closed instead of silently accepting the token.
    """

    if not jti:
        # A token without a jti cannot be revoked. Tokens issued before
        # the jti claim existed are the only case that reaches here.
        return False

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT revocation_id
            FROM revoked_tokens
            WHERE jti = %s
            """,
            (jti,)
        )

        return cursor.fetchone() is not None

    except mysql.connector.Error as error:
        logger.error(
            "Could not read the revocation store (run migration 006): %s",
            error
        )
        raise RevocationUnavailable(str(error)) from error

    finally:
        _close(cursor, connection)


def cleanup_expired():
    """
    Delete revocation rows whose token has already expired.

    Safe by construction: a token is rejected by the JWT expiry check
    before the revocation store is consulted, so a row for an expired
    token can never be the reason a token is refused.

    A one minute grace period covers a small clock difference between
    the application server and the database server, so a row is never
    removed while its token could still be accepted.
    """

    connection = None
    cursor = None

    try:
        connection = get_db()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM revoked_tokens
            WHERE expires_at < TIMESTAMPADD(MINUTE, -1, NOW())
            """
        )

        removed = cursor.rowcount
        connection.commit()

        if removed:
            logger.info("Removed %s expired token revocation(s)", removed)

        return removed

    except mysql.connector.Error as error:
        logger.error("Could not clean up expired revocations: %s", error)
        return 0

    finally:
        _close(cursor, connection)
