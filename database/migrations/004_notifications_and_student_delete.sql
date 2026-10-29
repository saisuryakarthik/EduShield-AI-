-- =====================================================================
-- EduShield AI — 004: in-app notifications + student soft-delete
--
-- Two independent, additive changes:
--
--   1. notifications — an in-app notification inbox addressed to a
--      single recipient (mentor or student). Rows are created by the
--      backend on security-relevant events. Messages never contain OTP
--      codes, link tokens, hashes, or parent phone numbers.
--
--   2. phone_change_requests.deleted_by_student — a soft-delete flag.
--      A student may hide a PENDING or CANCELLED request from their own
--      list; the row is never removed. Mentors and admins still see it.
--
-- Both changes are backward compatible: existing rows get
-- deleted_by_student = 0, and no existing table is altered destructively.
--
-- Run order: after 001 and 002. Take a backup first. See the matching
-- rollback file to reverse this migration.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. In-app notifications
-- ---------------------------------------------------------------------

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
    CONSTRAINT fk_notifications_user
        FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_notifications_request
        FOREIGN KEY (request_id)
        REFERENCES phone_change_requests (request_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- 2. Student soft-delete flag on phone change requests
-- ---------------------------------------------------------------------

ALTER TABLE phone_change_requests
    ADD COLUMN deleted_by_student TINYINT(1) NOT NULL DEFAULT 0;
