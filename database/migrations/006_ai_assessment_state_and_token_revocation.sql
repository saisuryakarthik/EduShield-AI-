-- =====================================================================
-- EduShield AI -- 006: AI assessment state and persistent token revocation
--
-- Two P1 fixes from the security/integration audit:
--
--   1. The AI assessment no longer shares a transaction with the parent
--      dual-OTP verification. ai_assessment_status is the durable state
--      machine for that assessment:
--          PENDING  -> COMPLETED   (assessment stored, request reviewable)
--          PENDING  -> FAILED      (assessment unavailable, request NOT
--                                   reviewable until a retry succeeds)
--      A request may only be approved when its assessment is COMPLETED,
--      so an AI failure can never be mistaken for a clean request.
--
--   2. JWT revocation moves from an in-process set to a table, so a
--      revoked token stays revoked across restarts and across the
--      workers of a multi-process server.
--
-- Nothing existing is dropped or rewritten. The only ALTER adds a
-- UNIQUE key on ai_assessments.request_id, so one request owns exactly
-- one assessment: a retry replaces the assessment instead of piling up
-- duplicate rows.
--
-- Run order: after 001, 002, 004 and 005. Take a backup first. See
-- 006_ai_assessment_state_and_token_revocation_rollback.sql to reverse
-- this migration.
--
-- MySQL 8: ALTER TABLE ... ADD UNIQUE KEY has no IF NOT EXISTS, so the
-- whole file is one-shot. Run it once.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. AI assessment state (one row per request)
--
-- Written in the same transaction that verifies the last parent OTP, so
-- a request can never reach COMPLETED verification without also
-- carrying the fact that an assessment is owed.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 2. Persistent token revocation
--
-- Only the token identifier (jti), the owning user, the revocation
-- time, the token's own expiry and an optional reason are stored.
-- No token, password, hash or secret is written here.
--
--   uq_revoked_jti       one row per token identifier: revoking the
--                         same token twice is a no-op, not an error.
--   idx_revoked_user     lookup by owner (audit, "revoke everything").
--   idx_revoked_expiry   cleanup of rows whose token has already
--                         expired.
-- ---------------------------------------------------------------------
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 3. One assessment per request
--
-- The assessment is a property of the request, not a log. Keeping only
-- the newest row per request makes the retry path idempotent: a retry
-- updates the existing row instead of creating a second one.
--
-- The DELETE below first removes older duplicates so the UNIQUE key can
-- be added safely. Only superseded duplicates are removed; the newest
-- assessment of every request is kept.
-- ---------------------------------------------------------------------
DELETE older FROM ai_assessments older
INNER JOIN ai_assessments newer
    ON older.request_id = newer.request_id
   AND older.assessment_id < newer.assessment_id;

ALTER TABLE ai_assessments
    ADD UNIQUE KEY uq_ai_assessment_request (request_id);
