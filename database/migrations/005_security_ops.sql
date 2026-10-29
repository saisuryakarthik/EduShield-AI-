-- =====================================================================
-- EduShield AI — 005: security operations, model governance and recovery
--
-- One migration, nine independent additions. Nothing existing is
-- dropped or rewritten; the only ALTERs widen two tables with nullable
-- columns, so old rows keep working unchanged.
--
--   1. model_registry       — one row per trained model version.
--   2. model_evaluations    — measured evaluation results per version.
--   3. model_predictions    — per-inference monitoring record.
--   4. security_alerts      — anomaly indicators raised by the system.
--   5. request_timeline     — structured, ordered request history.
--   6. account_recoveries   — controlled emergency account recovery.
--   7. sis_import_reports   — per-run, previewable import error report.
--   8. notification_deliveries — external delivery attempts for in-app
--                                notifications (optional, off by default).
--   9. request_sla_policies — configurable reminder/escalation windows.
--
-- Run order: after 001, 002 and 004. Take a backup first. See
-- 005_security_ops_rollback.sql to reverse this migration.
--
-- MySQL 8: ALTER TABLE ... ADD COLUMN has no IF NOT EXISTS, so the two
-- ALTER statements are one-shot. Run the whole file once.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Model registry (versioning)
--
-- One row per trained artifact. Exactly one row may have
-- status = 'active' at a time; the application enforces that when it
-- promotes a version.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 2. Model evaluations (measured, not asserted)
--
-- Rows are written by backend/scripts/evaluate_model.py from a real
-- group-aware split of the training dataset. The admin dashboard reads
-- these rows; it never recomputes metrics from thin air.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 3. Model predictions (monitoring)
--
-- One row per scored request: which model version produced the score,
-- how long it took, and the exact feature vector that was fed in. The
-- feature snapshot is what makes an assessment explainable after the
-- fact.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 4. Security alerts (anomaly indicators)
--
-- Raised by the rule engine and by the student "report suspicious
-- activity" action. A row is an open security concern until it is
-- acknowledged and resolved; a request pointed at by an open alert of
-- severity 'critical' is frozen from approval.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 5. Request timeline (structured history)
--
-- A denormalised, ordered view of a request's life. It is written in
-- the same transaction as the event it describes, so the timeline can
-- never disagree with audit_logs. `details_json` holds the structured
-- payload (never OTP codes or hashes).
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 6. Account recoveries (emergency access)
--
-- Controlled recovery: an admin starts a recovery, the account holder
-- proves their identity with a code sent to their registered email (and
-- optionally their registered phone), and only then is the password
-- reset. Every transition is written to audit_logs as well.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 7. SIS import reports (preview + error report)
--
-- One row per import attempt, including dry runs. `report_json` holds
-- the row-by-row plan (create / update / skip / error) so an admin can
-- preview before committing, and read the error report afterwards.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 8. Notification deliveries (optional external delivery)
--
-- The in-app inbox is the source of truth. These rows record whether a
-- copy was also pushed outside the app (email or webhook) and whether
-- that push succeeded. Nothing here is required for the inbox to work.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 9. Request SLA policies (reminders and escalation)
--
-- One row per policy. `reminder_after_hours` triggers a nudge to the
-- assigned mentor; `escalate_after_hours` hands the request to the
-- admin queue. A disabled policy is ignored by the scheduler.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Default policy: remind the assigned mentor after 24h, escalate to the
-- admin queue after 72h.
INSERT INTO request_sla_policies
    (name, reminder_after_hours, escalate_after_hours, notify_admin)
VALUES
    ('default', 24, 72, 1);

-- ---------------------------------------------------------------------
-- 10. Widen notifications with external-delivery bookkeeping
--
-- All nullable with defaults, so existing rows stay valid.
-- ---------------------------------------------------------------------
ALTER TABLE notifications
    ADD COLUMN delivery_status   VARCHAR(20) NOT NULL DEFAULT 'not_requested',
    ADD COLUMN delivery_channel  VARCHAR(20) NULL,
    ADD COLUMN delivery_error    VARCHAR(500) NULL,
    ADD COLUMN delivered_at      DATETIME NULL;

-- ---------------------------------------------------------------------
-- 11. Widen sis_import_runs with a link to the detailed report
-- ---------------------------------------------------------------------
ALTER TABLE sis_import_runs
    ADD COLUMN report_id INT NULL;
