"""
Real-database test harness for the EduShield backend.

No fake DB: every test in this suite talks to a real MySQL schema. To
make that safe the harness:

    * refuses to run unless the target database is named exactly as the
      caller's ``EDUSHIELD_TEST_DB_NAME`` (see _load_test_config);
    * refuses to run against the preserved ``edushield_test`` database or
      the live ``edushieldai`` database, and requires the name to start
      with ``edushield_test_`` so it is clearly disposable;
    * re-checks the connected database immediately before any table is
      truncated;
    * builds the schema from the project's base DDL plus migrations 001
      and 002, so the test schema matches the live one;
    * truncates every table between tests and re-seeds the shared
      fixtures, so tests are isolated without recreating the schema.

The base DDL for the eight pre-001 tables is not stored in the
repository, so ``BASE_SCHEMA`` below is a faithful copy of the live
``SHOW CREATE TABLE`` output (captured from the ``edushieldai``
database). Keep it in sync if the base schema ever changes.
"""

import os
import sys
import unittest
from urllib.parse import urlparse

import mysql.connector

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# Load backend/.env so TEST_DATABASE_URL is available without the caller
# having to export it. Does not override an already-set value.
try:
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv(os.path.join(BACKEND_DIR, ".env"), override=False)
except Exception:  # pragma: no cover - dotenv is already a dependency
    pass


TEST_URL_ENV = "TEST_DATABASE_URL"
DISPOSABLE_DB_ENV = "EDUSHIELD_TEST_DB_NAME"
# Never destructive: the preserved regression database and the live app.
RESERVED_DB_NAMES = frozenset({"edushield_test", "edushieldai"})
DISPOSABLE_DB_PREFIX = "edushield_test_"


def _load_test_config():
    """
    Parse TEST_DATABASE_URL and refuse any non-disposable target.

    Running these suites truncates every table. They therefore require
    two independent opt-ins:

      * TEST_DATABASE_URL points at the database to use;
      * EDUSHIELD_TEST_DB_NAME names exactly that database.

    Missing opt-ins skip the suite; a reserved or mismatched name is a
    hard error so a misconfiguration can never silently truncate a real
    database.
    """

    raw = os.getenv(TEST_URL_ENV)

    if not raw:
        raise unittest.SkipTest(
            f"{TEST_URL_ENV} is not set; real-DB tests cannot run."
        )

    parsed = urlparse(raw)

    if parsed.scheme != "mysql":
        raise RuntimeError(
            f"{TEST_URL_ENV} must use the mysql scheme, got "
            f"{parsed.scheme!r}."
        )

    database = (parsed.path or "").lstrip("/")
    designated = os.getenv(DISPOSABLE_DB_ENV)

    if not designated:
        raise unittest.SkipTest(
            f"{DISPOSABLE_DB_ENV} is not set; refusing to truncate "
            f"{database!r}. Set it to a dedicated disposable database "
            f"named {DISPOSABLE_DB_PREFIX}*."
        )

    if database in RESERVED_DB_NAMES or designated in RESERVED_DB_NAMES:
        raise RuntimeError(
            f"Refusing destructive tests against reserved database "
            f"{database!r}. Use a dedicated disposable database named "
            f"{DISPOSABLE_DB_PREFIX}*."
        )

    if not database.startswith(DISPOSABLE_DB_PREFIX):
        raise RuntimeError(
            f"Refusing destructive tests against database {database!r}; "
            f"the name must start with {DISPOSABLE_DB_PREFIX!r}."
        )

    if designated != database:
        raise RuntimeError(
            f"{DISPOSABLE_DB_ENV}={designated!r} does not match "
            f"{TEST_URL_ENV} database {database!r}."
        )

    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": database,
    }


# ------------------------------------------------------------------
# Base DDL (pre-001), copied from the live edushieldai schema.
# ------------------------------------------------------------------

BASE_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id        VARCHAR(20)  NOT NULL,
        name           VARCHAR(100) NOT NULL,
        email          VARCHAR(150) NOT NULL,
        parent_email   VARCHAR(150) DEFAULT NULL,
        parent_phone   VARCHAR(20)  DEFAULT NULL,
        phone_number   VARCHAR(15)  NOT NULL,
        mentor_id      VARCHAR(20)  DEFAULT NULL,
        created_at     TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
        role           ENUM('student','mentor') NOT NULL DEFAULT 'student',
        password_hash  VARCHAR(255) NOT NULL,
        PRIMARY KEY (user_id),
        UNIQUE KEY email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS phone_change_requests (
        request_id                VARCHAR(30) NOT NULL,
        user_id                   VARCHAR(20) NOT NULL,
        old_phone                 VARCHAR(15) NOT NULL,
        new_phone                 VARCHAR(15) NOT NULL,
        requested_at              TIMESTAMP   NULL DEFAULT CURRENT_TIMESTAMP,
        auth_status               ENUM('PENDING','VERIFIED','FAILED')
                                  NOT NULL DEFAULT 'PENDING',
        parent_verification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        parent_verified_at        TIMESTAMP   NULL DEFAULT NULL,
        parent_token_hash         VARCHAR(64) DEFAULT NULL,
        parent_token_expires_at   TIMESTAMP   NULL DEFAULT NULL,
        status                    VARCHAR(30) NOT NULL DEFAULT 'PENDING',
        mentor_id                 VARCHAR(20) DEFAULT NULL,
        reviewed_at               TIMESTAMP   NULL DEFAULT NULL,
        rejection_reason          TEXT,
        otp                       VARCHAR(6)  NULL,
        otp_expires_at            DATETIME    NULL,
        PRIMARY KEY (request_id),
        KEY fk_phone_request_user (user_id),
        CONSTRAINT fk_phone_request_user
            FOREIGN KEY (user_id) REFERENCES users (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_assessments (
        assessment_id BIGINT NOT NULL AUTO_INCREMENT,
        request_id    VARCHAR(30) NOT NULL,
        risk_score    FLOAT NOT NULL,
        risk_level    ENUM('LOW','MEDIUM','HIGH') NOT NULL,
        risk_factors  JSON DEFAULT NULL,
        model_version VARCHAR(30) DEFAULT NULL,
        assessed_at   TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (assessment_id),
        KEY fk_ai_request (request_id),
        CONSTRAINT fk_ai_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id),
        CONSTRAINT chk_risk_score
            CHECK (risk_score >= 0 AND risk_score <= 100)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        log_id     BIGINT NOT NULL AUTO_INCREMENT,
        request_id VARCHAR(30) DEFAULT NULL,
        user_id    VARCHAR(20) DEFAULT NULL,
        actor      VARCHAR(20) NOT NULL,
        action     VARCHAR(50) NOT NULL,
        details    JSON DEFAULT NULL,
        timestamp  TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (log_id),
        KEY fk_audit_request (request_id),
        KEY fk_audit_user (user_id),
        CONSTRAINT fk_audit_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id),
        CONSTRAINT fk_audit_user FOREIGN KEY (user_id)
            REFERENCES users (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS mentor_reviews (
        review_id   BIGINT NOT NULL AUTO_INCREMENT,
        request_id  VARCHAR(30) NOT NULL,
        mentor_id   VARCHAR(20) NOT NULL,
        decision    ENUM('APPROVED','REJECTED') NOT NULL,
        reason      TEXT,
        reviewed_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (review_id),
        KEY fk_mentor_request (request_id),
        CONSTRAINT fk_mentor_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS security_context (
        context_id              BIGINT NOT NULL AUTO_INCREMENT,
        request_id              VARCHAR(30) NOT NULL,
        known_device            TINYINT(1) NOT NULL,
        location_deviation      FLOAT NOT NULL,
        failed_login_count      INT NOT NULL,
        recent_password_reset   TINYINT(1) NOT NULL,
        mfa_verified            TINYINT(1) NOT NULL,
        phone_change_frequency  INT NOT NULL,
        login_time_deviation    FLOAT NOT NULL,
        trust_score             FLOAT NOT NULL,
        captured_at             TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (context_id),
        KEY fk_security_request (request_id),
        CONSTRAINT fk_security_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id),
        CONSTRAINT chk_failed_login_count CHECK (failed_login_count >= 0),
        CONSTRAINT chk_location_deviation CHECK (location_deviation >= 0),
        CONSTRAINT chk_login_time_deviation CHECK (login_time_deviation >= 0),
        CONSTRAINT chk_phone_change_frequency CHECK (phone_change_frequency >= 0),
        CONSTRAINT chk_trust_score CHECK (trust_score >= 0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS security_events (
        event_id   BIGINT NOT NULL AUTO_INCREMENT,
        user_id    VARCHAR(20) NOT NULL,
        event_type VARCHAR(40) NOT NULL,
        success    TINYINT(1) NOT NULL DEFAULT 1,
        device_id  VARCHAR(255) DEFAULT NULL,
        ip_address VARCHAR(45) DEFAULT NULL,
        user_agent TEXT,
        latitude   DECIMAL(10,7) DEFAULT NULL,
        longitude  DECIMAL(10,7) DEFAULT NULL,
        created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (event_id),
        KEY idx_security_user (user_id),
        KEY idx_security_user_event (user_id, event_type),
        CONSTRAINT fk_security_event_user FOREIGN KEY (user_id)
            REFERENCES users (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


# 001-equivalent table creation. The ALTERs from 001 are already baked
# into BASE_SCHEMA (parent_phone, widened status, nullable otp columns),
# so only the new table needs creating here.
MIGRATION_001 = [
    """
    CREATE TABLE IF NOT EXISTS phone_change_otps (
        otp_id       INT AUTO_INCREMENT PRIMARY KEY,
        request_id   VARCHAR(20) NOT NULL,
        channel      ENUM('SMS','EMAIL') NOT NULL,
        code_hash    CHAR(64) NULL,
        expires_at   DATETIME NOT NULL,
        attempts     INT NOT NULL DEFAULT 0,
        max_attempts INT NOT NULL DEFAULT 3,
        locked       TINYINT(1) NOT NULL DEFAULT 0,
        verified     TINYINT(1) NOT NULL DEFAULT 0,
        verified_at  DATETIME NULL,
        created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_request_channel (request_id, channel),
        CONSTRAINT fk_phone_change_otps_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


# 002-equivalent DDL, mirroring database/migrations/002_sis_onboarding.sql.
MIGRATION_002 = [
    """
    ALTER TABLE users
        MODIFY COLUMN role
            ENUM('student','mentor','admin') NOT NULL DEFAULT 'student'
    """,
    """
    ALTER TABLE users
        ADD COLUMN institutional_email VARCHAR(150) NULL,
        ADD COLUMN external_id         VARCHAR(32)  NULL,
        ADD COLUMN department          VARCHAR(100) NULL,
        ADD COLUMN section             VARCHAR(20)  NULL,
        ADD COLUMN year                VARCHAR(20)  NULL,
        ADD COLUMN account_status
            ENUM('pending_activation','active','disabled')
            NOT NULL DEFAULT 'pending_activation'
    """,
    """
    ALTER TABLE users
        ADD UNIQUE KEY uq_users_institutional_email (institutional_email),
        ADD UNIQUE KEY uq_users_external_id (external_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS mentor_assignments (
        assignment_id INT AUTO_INCREMENT PRIMARY KEY,
        student_id    VARCHAR(20) NOT NULL,
        mentor_id     VARCHAR(20) NOT NULL,
        assigned_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        active        TINYINT(1) NOT NULL DEFAULT 1,
        UNIQUE KEY uq_assignment_student (student_id),
        KEY idx_assignment_mentor (mentor_id),
        CONSTRAINT fk_assignment_student FOREIGN KEY (student_id)
            REFERENCES users (user_id) ON DELETE CASCADE,
        CONSTRAINT fk_assignment_mentor FOREIGN KEY (mentor_id)
            REFERENCES users (user_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS account_activation_otps (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        user_id    VARCHAR(20) NOT NULL,
        code_hash  CHAR(64) NULL,
        attempts   INT NOT NULL DEFAULT 0,
        locked     TINYINT(1) NOT NULL DEFAULT 0,
        used       TINYINT(1) NOT NULL DEFAULT 0,
        expires_at DATETIME NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_activation_user (user_id),
        CONSTRAINT fk_activation_user FOREIGN KEY (user_id)
            REFERENCES users (user_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS sis_import_runs (
        run_id              INT AUTO_INCREMENT PRIMARY KEY,
        started_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at         DATETIME NULL,
        students_read       INT NOT NULL DEFAULT 0,
        students_created    INT NOT NULL DEFAULT 0,
        students_updated    INT NOT NULL DEFAULT 0,
        mentors_read        INT NOT NULL DEFAULT 0,
        mentors_created     INT NOT NULL DEFAULT 0,
        mentors_updated     INT NOT NULL DEFAULT 0,
        assignments_created INT NOT NULL DEFAULT 0,
        assignments_updated INT NOT NULL DEFAULT 0,
        unassigned          INT NOT NULL DEFAULT 0,
        errors_json         JSON NULL,
        run_by              VARCHAR(150) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


# 004-equivalent DDL, mirroring database/migrations/004_*.sql.
MIGRATION_004 = [
    """
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id BIGINT NOT NULL AUTO_INCREMENT,
        user_id         VARCHAR(20) NOT NULL,
        type            VARCHAR(40) NOT NULL,
        request_id      VARCHAR(30) DEFAULT NULL,
        message         VARCHAR(500) NOT NULL,
        created_at      TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
        read_at         TIMESTAMP NULL DEFAULT NULL,
        PRIMARY KEY (notification_id),
        KEY idx_notifications_user (user_id),
        KEY idx_notifications_user_unread (user_id, read_at),
        KEY fk_notifications_request (request_id),
        CONSTRAINT fk_notifications_user FOREIGN KEY (user_id)
            REFERENCES users (user_id) ON DELETE CASCADE,
        CONSTRAINT fk_notifications_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    ALTER TABLE phone_change_requests
        ADD COLUMN deleted_by_student TINYINT(1) NOT NULL DEFAULT 0
    """,
]


# 005-equivalent DDL, mirroring database/migrations/005_security_ops.sql.
MIGRATION_005 = [
    """
    CREATE TABLE IF NOT EXISTS model_registry (
        model_id       INT AUTO_INCREMENT PRIMARY KEY,
        model_version  VARCHAR(40)  NOT NULL,
        model_type     VARCHAR(40)  NOT NULL,
        status         ENUM('active','retired','archived')
                       NOT NULL DEFAULT 'active',
        artifact_hash  CHAR(64)     NULL,
        feature_list   JSON         NULL,
        risk_threshold FLOAT        NOT NULL DEFAULT 50,
        dataset_name   VARCHAR(120) NULL,
        trained_at     DATETIME     NULL,
        registered_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notes          TEXT         NULL,
        UNIQUE KEY uq_model_version (model_version),
        KEY idx_model_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS model_evaluations (
        evaluation_id  INT AUTO_INCREMENT PRIMARY KEY,
        model_version  VARCHAR(40)  NOT NULL,
        dataset_name   VARCHAR(120) NOT NULL,
        evaluated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        test_samples   INT          NOT NULL DEFAULT 0,
        test_users     INT          NOT NULL DEFAULT 0,
        train_samples  INT          NOT NULL DEFAULT 0,
        train_users    INT          NOT NULL DEFAULT 0,
        user_overlap   INT          NOT NULL DEFAULT 0,
        accuracy       FLOAT        NOT NULL DEFAULT 0,
        precision_score FLOAT       NOT NULL DEFAULT 0,
        recall_score   FLOAT        NOT NULL DEFAULT 0,
        f1             FLOAT        NOT NULL DEFAULT 0,
        roc_auc        FLOAT        NOT NULL DEFAULT 0,
        confusion_json JSON         NULL,
        threshold_json JSON         NULL,
        notes          TEXT         NULL,
        KEY idx_evaluation_model (model_version),
        KEY idx_evaluation_time (evaluated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS model_predictions (
        prediction_id  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        request_id     VARCHAR(30) NOT NULL,
        user_id        VARCHAR(20) DEFAULT NULL,
        model_version  VARCHAR(40) NOT NULL,
        risk_score     FLOAT        NOT NULL,
        risk_level     VARCHAR(10)  NOT NULL,
        latency_ms     FLOAT        NOT NULL DEFAULT 0,
        feature_values JSON         NULL,
        predicted_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_prediction_request (request_id),
        KEY idx_prediction_model (model_version),
        KEY idx_prediction_time (predicted_at),
        CONSTRAINT fk_prediction_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS security_alerts (
        alert_id        BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        request_id      VARCHAR(30) DEFAULT NULL,
        user_id         VARCHAR(20) DEFAULT NULL,
        alert_type      VARCHAR(60) NOT NULL,
        severity        ENUM('info','warning','critical') NOT NULL DEFAULT 'info',
        source          ENUM('system','student','mentor','admin')
                        NOT NULL DEFAULT 'system',
        message         VARCHAR(500) NOT NULL,
        indicators_json JSON         NULL,
        status          ENUM('open','acknowledged','resolved')
                        NOT NULL DEFAULT 'open',
        raised_by       VARCHAR(20)  DEFAULT NULL,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        acknowledged_by VARCHAR(20)  DEFAULT NULL,
        acknowledged_at DATETIME     NULL,
        resolved_by     VARCHAR(20)  DEFAULT NULL,
        resolved_at     DATETIME     NULL,
        resolution_note VARCHAR(500) NULL,
        KEY idx_alert_status (status),
        KEY idx_alert_request (request_id),
        KEY idx_alert_user (user_id),
        CONSTRAINT fk_alert_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS request_timeline (
        timeline_id    BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        request_id     VARCHAR(30) NOT NULL,
        event_type     VARCHAR(60) NOT NULL,
        category       ENUM('submitted','verification','ai','alert',
                            'decision','notification','recovery','system')
                        NOT NULL DEFAULT 'system',
        actor_type     ENUM('student','mentor','admin','parent','system')
                        NOT NULL DEFAULT 'system',
        actor_id       VARCHAR(20)  DEFAULT NULL,
        title          VARCHAR(160) NOT NULL,
        summary        VARCHAR(500) DEFAULT NULL,
        details_json   JSON         NULL,
        created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_timeline_request (request_id, created_at),
        CONSTRAINT fk_timeline_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS account_recoveries (
        recovery_id     BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        user_id         VARCHAR(20) NOT NULL,
        requested_by    VARCHAR(20) NOT NULL,
        reason          VARCHAR(500) NOT NULL,
        status          ENUM('pending','verified','completed',
                            'expired','revoked','failed')
                        NOT NULL DEFAULT 'pending',
        code_hash       CHAR(64)     NULL,
        attempts        INT          NOT NULL DEFAULT 0,
        max_attempts    INT          NOT NULL DEFAULT 3,
        locked          TINYINT(1)   NOT NULL DEFAULT 0,
        verified_at     DATETIME     NULL,
        completed_at    DATETIME     NULL,
        expires_at      DATETIME     NOT NULL,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_recovery_user (user_id),
        KEY idx_recovery_status (status),
        CONSTRAINT fk_recovery_user FOREIGN KEY (user_id)
            REFERENCES users (user_id) ON DELETE CASCADE,
        CONSTRAINT fk_recovery_requester FOREIGN KEY (requested_by)
            REFERENCES users (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS sis_import_reports (
        report_id      INT AUTO_INCREMENT PRIMARY KEY,
        run_id         INT          NULL,
        dry_run        TINYINT(1)   NOT NULL DEFAULT 1,
        students_file  VARCHAR(255) NULL,
        mentors_file   VARCHAR(255) NULL,
        students_read  INT          NOT NULL DEFAULT 0,
        mentors_read   INT          NOT NULL DEFAULT 0,
        created_count  INT          NOT NULL DEFAULT 0,
        updated_count  INT          NOT NULL DEFAULT 0,
        skipped_count  INT          NOT NULL DEFAULT 0,
        error_count    INT          NOT NULL DEFAULT 0,
        warning_count  INT          NOT NULL DEFAULT 0,
        report_json    JSON         NULL,
        run_by         VARCHAR(150) NULL,
        created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_import_report_run (run_id),
        KEY idx_import_report_time (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_deliveries (
        delivery_id     BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        notification_id BIGINT      NOT NULL,
        channel         ENUM('email','webhook') NOT NULL,
        status          ENUM('pending','delivered','failed','skipped')
                        NOT NULL DEFAULT 'pending',
        error_message   VARCHAR(500) NULL,
        delivered_at    DATETIME     NULL,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_delivery_notification (notification_id),
        KEY idx_delivery_status (status),
        CONSTRAINT fk_delivery_notification FOREIGN KEY (notification_id)
            REFERENCES notifications (notification_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS request_sla_policies (
        policy_id           INT AUTO_INCREMENT PRIMARY KEY,
        name                VARCHAR(60)  NOT NULL,
        reminder_after_hours INT         NOT NULL DEFAULT 24,
        escalate_after_hours INT         NOT NULL DEFAULT 72,
        notify_admin        TINYINT(1)   NOT NULL DEFAULT 1,
        enabled             TINYINT(1)   NOT NULL DEFAULT 1,
        updated_by          VARCHAR(20)  DEFAULT NULL,
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_sla_enabled (enabled)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    INSERT INTO request_sla_policies
        (name, reminder_after_hours, escalate_after_hours, notify_admin)
    VALUES
        ('default', 24, 72, 1)
    """,
    """
    ALTER TABLE notifications
        ADD COLUMN delivery_status   VARCHAR(20) NOT NULL DEFAULT 'not_requested',
        ADD COLUMN delivery_channel  VARCHAR(20) NULL,
        ADD COLUMN delivery_error    VARCHAR(500) NULL,
        ADD COLUMN delivered_at      DATETIME NULL
    """,
    """
    ALTER TABLE sis_import_runs
        ADD COLUMN report_id INT NULL
    """,
]


# 006-equivalent DDL, mirroring
# database/migrations/006_ai_assessment_state_and_token_revocation.sql.
MIGRATION_006 = [
    """
    CREATE TABLE IF NOT EXISTS ai_assessment_status (
        request_id      VARCHAR(30) NOT NULL,
        status          ENUM('PENDING','COMPLETED','FAILED')
                        NOT NULL DEFAULT 'PENDING',
        attempts        INT          NOT NULL DEFAULT 0,
        last_error      VARCHAR(500) NULL,
        last_attempt_at DATETIME     NULL,
        completed_at    DATETIME     NULL,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (request_id),
        KEY idx_ai_assessment_status (status),
        KEY idx_ai_assessment_updated (updated_at),
        CONSTRAINT fk_ai_status_request FOREIGN KEY (request_id)
            REFERENCES phone_change_requests (request_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS revoked_tokens (
        revocation_id BIGINT      NOT NULL AUTO_INCREMENT,
        jti           VARCHAR(64) NOT NULL,
        user_id       VARCHAR(20) NOT NULL,
        revoked_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at    DATETIME    NOT NULL,
        reason        VARCHAR(120) NULL,
        PRIMARY KEY (revocation_id),
        UNIQUE KEY uq_revoked_jti (jti),
        KEY idx_revoked_user (user_id),
        KEY idx_revoked_expiry (expires_at),
        CONSTRAINT fk_revoked_token_user FOREIGN KEY (user_id)
            REFERENCES users (user_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


# 007-equivalent DDL, mirroring
# database/migrations/007_schema_migration_ledger.sql.
MIGRATION_007 = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version      VARCHAR(20)  NOT NULL,
        name         VARCHAR(191) NOT NULL,
        checksum     CHAR(64)     NULL,
        status       ENUM('applied','deferred','failed')
                     NOT NULL DEFAULT 'applied',
        applied_at   DATETIME     NULL,
        verified_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        applied_by   VARCHAR(150) NULL,
        notes        VARCHAR(255) NULL,
        PRIMARY KEY (version)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    INSERT INTO schema_migrations
        (version, name, checksum, status, applied_at, applied_by, notes)
    VALUES
        ('001', 'dual_parent_otp', NULL, 'applied', NULL,
         'test-harness', 'Schema contract test fixture.'),
        ('002', 'sis_onboarding', NULL, 'applied', NULL,
         'test-harness', 'Schema contract test fixture.'),
        ('003', 'drop_users_mentor_id', NULL, 'deferred', NULL,
         'test-harness', 'Intentionally deferred.'),
        ('004', 'notifications_and_student_delete', NULL, 'applied', NULL,
         'test-harness', 'Schema contract test fixture.'),
        ('005', 'security_ops', NULL, 'applied', NULL,
         'test-harness', 'Schema contract test fixture.'),
        ('006', 'ai_assessment_state_and_token_revocation', NULL, 'applied',
         NULL, 'test-harness', 'Schema contract test fixture.'),
        ('007', 'schema_migration_ledger', NULL, 'applied', NULL,
         'test-harness', 'Schema contract test fixture.')
    ON DUPLICATE KEY UPDATE name = VALUES(name)
    """,
]


ALL_TABLES = [
    "notification_deliveries",
    "sis_import_reports",
    "account_recoveries",
    "request_timeline",
    "security_alerts",
    "model_predictions",
    "model_evaluations",
    "model_registry",
    "request_sla_policies",
    "notifications",
    "account_activation_otps",
    "sis_import_runs",
    "mentor_assignments",
    "phone_change_otps",
    "ai_assessment_status",
    "ai_assessments",
    "revoked_tokens",
    "audit_logs",
    "mentor_reviews",
    "security_context",
    "security_events",
    "phone_change_requests",
    "users",
]


def connect(config=None):
    """Open a new connection to the test database."""

    return mysql.connector.connect(**(config or _load_test_config()))


def _table_exists(cursor, table):
    cursor.execute("SHOW TABLES LIKE %s", (table,))
    return cursor.fetchone() is not None


def _column_exists(cursor, table, column):
    cursor.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
    return cursor.fetchone() is not None


def _index_exists(cursor, table, index):
    cursor.execute(
        "SELECT 1 FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
        "AND INDEX_NAME = %s",
        (table, index),
    )
    return cursor.fetchone() is not None


def ensure_schema(connection):
    """Create the test schema if it is not already present."""

    cursor = connection.cursor()

    try:
        if not _table_exists(cursor, "users"):
            for statement in BASE_SCHEMA:
                cursor.execute(statement)

        if not _table_exists(cursor, "phone_change_otps"):
            for statement in MIGRATION_001:
                cursor.execute(statement)

        if not _table_exists(cursor, "mentor_assignments"):
            for statement in MIGRATION_002:
                cursor.execute(statement)

        # 004 has one table and one column; guard each independently so
        # the migration is safe to run against a partially-upgraded schema.
        if not _table_exists(cursor, "notifications"):
            cursor.execute(MIGRATION_004[0])

        if not _column_exists(
            cursor, "phone_change_requests", "deleted_by_student"
        ):
            cursor.execute(MIGRATION_004[1])

        # 005 creates nine tables and widens two. Each piece is guarded
        # separately so the harness is safe against a partially-upgraded
        # schema.
        for statement in MIGRATION_005[:9]:
            table = statement.split("IF NOT EXISTS ", 1)[1].split(" ", 1)[0]
            if not _table_exists(cursor, table):
                cursor.execute(statement)

        if not _column_exists(
            cursor, "notifications", "delivery_status"
        ):
            cursor.execute(MIGRATION_005[10])

        if not _column_exists(
            cursor, "sis_import_runs", "report_id"
        ):
            cursor.execute(MIGRATION_005[11])

        # The default SLA policy is an INSERT, not DDL: keep exactly one.
        cursor.execute(
            "SELECT COUNT(*) FROM request_sla_policies WHERE name = 'default'"
        )
        if (cursor.fetchone() or [0])[0] == 0:
            cursor.execute(MIGRATION_005[9])

        # 006 adds the AI assessment state machine and the persistent
        # token revocation table.
        for statement in MIGRATION_006:
            table = statement.split("IF NOT EXISTS ", 1)[1].split(" ", 1)[0]
            if not _table_exists(cursor, table):
                cursor.execute(statement)

        # One assessment per request, so a retry updates the existing
        # row instead of creating a second one. Older duplicates are
        # removed first, exactly as the migration does.
        if not _index_exists(
            cursor, "ai_assessments", "uq_ai_assessment_request"
        ):
            cursor.execute(
                "DELETE older FROM ai_assessments older "
                "INNER JOIN ai_assessments newer "
                "ON older.request_id = newer.request_id "
                "AND older.assessment_id < newer.assessment_id"
            )
            cursor.execute(
                "ALTER TABLE ai_assessments "
                "ADD UNIQUE KEY uq_ai_assessment_request (request_id)"
            )

        # 007 is the migration ledger. It is intentionally not truncated
        # between tests; the harness upserts its baseline rows instead.
        for statement in MIGRATION_007:
            cursor.execute(statement)

        connection.commit()
    finally:
        cursor.close()


def _assert_destructive_target(cursor):
    """Re-check the live connection target before truncating anything."""

    cursor.execute("SELECT DATABASE()")
    current = (cursor.fetchone() or [None])[0]
    designated = os.getenv(DISPOSABLE_DB_ENV)

    if not current:
        raise RuntimeError(
            "Refusing to truncate: the connection has no selected database."
        )

    if current in RESERVED_DB_NAMES:
        raise RuntimeError(
            f"Refusing to truncate reserved database {current!r}."
        )

    if not current.startswith(DISPOSABLE_DB_PREFIX):
        raise RuntimeError(
            f"Refusing to truncate database {current!r}; the name must "
            f"start with {DISPOSABLE_DB_PREFIX!r}."
        )

    if designated != current:
        raise RuntimeError(
            f"Refusing to truncate database {current!r}: it does not "
            f"match {DISPOSABLE_DB_ENV}={designated!r}."
        )


def truncate_all(connection):
    """Empty every table so each test starts from a known state."""

    cursor = connection.cursor()

    try:
        _assert_destructive_target(cursor)
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in ALL_TABLES:
            cursor.execute(f"TRUNCATE TABLE {table}")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        connection.commit()
    finally:
        cursor.close()


def shift_time(connection, seconds):
    """
    Move the clock forward *seconds* for OTP expiry tests.

    The application computes expiry with MySQL NOW(), so the only way to
    age rows from a test is to rewind their stored timestamps. This
    subtracts *seconds* from every time-bearing column so that rows
    created *now* look *seconds* old.
    """

    cursor = connection.cursor()

    try:
        cursor.execute(
            "UPDATE phone_change_otps "
            "SET expires_at = TIMESTAMPADD(SECOND, -%s, expires_at)",
            (seconds,)
        )
        cursor.execute(
            "UPDATE phone_change_requests "
            "SET parent_token_expires_at = "
            "    TIMESTAMPADD(SECOND, -%s, parent_token_expires_at) "
            "WHERE parent_token_expires_at IS NOT NULL",
            (seconds,)
        )
        cursor.execute(
            "UPDATE account_activation_otps "
            "SET created_at = TIMESTAMPADD(SECOND, -%s, created_at), "
            "    expires_at = TIMESTAMPADD(SECOND, -%s, expires_at)",
            (seconds, seconds)
        )
        cursor.execute(
            "UPDATE revoked_tokens "
            "SET expires_at = TIMESTAMPADD(SECOND, -%s, expires_at)",
            (seconds,)
        )
        connection.commit()
    finally:
        cursor.close()


# ------------------------------------------------------------------
# Shared fixture seeding
# ------------------------------------------------------------------

def add_user(connection, *, user_id, name, email, role="student",
             password_hash="x", account_status="active",
             phone_number="9000000000", parent_email=None,
             parent_phone=None, department=None, section=None, year=None):
    """Insert a user row directly (bypassing the API)."""

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO users
            (
                user_id, name, email, role, password_hash, account_status,
                phone_number, parent_email, parent_phone,
                institutional_email, external_id, department, section, year
            )
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, name, email, role, password_hash, account_status,
                phone_number, parent_email, parent_phone,
                email, user_id, department, section, year,
            )
        )
        connection.commit()
    finally:
        cursor.close()


def add_assignment(connection, student_id, mentor_id, active=1):
    """Create (or replace) a student's mentor assignment."""

    cursor = connection.cursor()
    try:
        cursor.execute(
            "DELETE FROM mentor_assignments WHERE student_id = %s",
            (student_id,)
        )
        cursor.execute(
            """
            INSERT INTO mentor_assignments (student_id, mentor_id, active)
            VALUES (%s, %s, %s)
            """,
            (student_id, mentor_id, active)
        )
        connection.commit()
    finally:
        cursor.close()


def add_request(connection, *, request_id, user_id, mentor_id,
                old_phone="9000000001", new_phone="9111222333",
                status="PENDING", auth_status="PENDING"):
    """Insert a phone_change_requests row directly."""

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO phone_change_requests
            (
                request_id, user_id, old_phone, new_phone,
                auth_status, parent_verification_status, status, mentor_id
            )
            VALUES
            (%s, %s, %s, %s, %s, 'PENDING', %s, %s)
            """,
            (
                request_id, user_id, old_phone, new_phone,
                auth_status, status, mentor_id,
            )
        )
        connection.commit()
    finally:
        cursor.close()


def fetch_one(connection, query, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        cursor.close()


def fetch_all(connection, query, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        cursor.close()


def fresh_fetch_one(config, query, params=()):
    """Run a SELECT on a brand-new connection (avoids stale snapshots)."""
    connection = connect(config)
    try:
        return fetch_one(connection, query, params)
    finally:
        connection.close()


def fresh_fetch_all(config, query, params=()):
    """Run a SELECT on a brand-new connection (avoids stale snapshots)."""
    connection = connect(config)
    try:
        return fetch_all(connection, query, params)
    finally:
        connection.close()


class RealDatabaseTestCase(unittest.TestCase):
    """Base class for tests that need the real test database."""

    # Set False by subclasses that do not want the default fixtures.
    seed_default_fixtures = True

    @classmethod
    def setUpClass(cls):
        cls.db_config = _load_test_config()
        cls.connection = connect(cls.db_config)
        ensure_schema(cls.connection)
        truncate_all(cls.connection)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def setUp(self):
        truncate_all(self.connection)
        if self.seed_default_fixtures:
            self.seed()
        self.after_setup()

    def seed(self):
        """Override to insert per-test fixtures."""

    def after_setup(self):
        """Override for extra setup (e.g. starting mock patches)."""
