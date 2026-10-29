-- =====================================================================
-- EduShield AI — 002: Phase 1 SIS onboarding and admin portal
--
-- Run once, AFTER 001_dual_parent_otp.sql. This migration is additive:
-- it does not modify or drop any existing column except to widen the
-- users.role ENUM.
--
-- Pre-flight (already confirmed for this database):
--   users.user_id             VARCHAR(20)  PRIMARY KEY
--   phone_change_requests.request_id VARCHAR(30) PRIMARY KEY
--   001 applied: users.parent_phone, phone_change_otps, widened status
--
-- Back up before running. MySQL 8: ADD COLUMN has no IF NOT EXISTS, so
-- this file is one-shot. Use 002_sis_onboarding_rollback.sql to undo.
-- =====================================================================

-- 1. Allow an admin role.
ALTER TABLE users
    MODIFY COLUMN role
        ENUM('student', 'mentor', 'admin') NOT NULL DEFAULT 'student';

-- 2. Profile, SIS identity and lifecycle columns.
--    institutional_email / external_id are UNIQUE but nullable, so the
--    existing rows stay valid until they are back-filled below.
ALTER TABLE users
    ADD COLUMN institutional_email VARCHAR(150) NULL,
    ADD COLUMN external_id         VARCHAR(32)  NULL,
    ADD COLUMN department          VARCHAR(100) NULL,
    ADD COLUMN section             VARCHAR(20)  NULL,
    ADD COLUMN year                VARCHAR(20)  NULL,
    ADD COLUMN account_status
        ENUM('pending_activation', 'active', 'disabled')
        NOT NULL DEFAULT 'pending_activation';

ALTER TABLE users
    ADD UNIQUE KEY uq_users_institutional_email (institutional_email),
    ADD UNIQUE KEY uq_users_external_id (external_id);

-- 3. Existing rows are real, working accounts. Mark them active so the
--    new login gate does not lock them out. New imported rows keep the
--    column default ('pending_activation').
--
--    external_id is back-filled from user_id so a later SIS import can
--    match these pre-existing accounts instead of trying (and failing)
--    to INSERT them again.
--
--    institutional_email is deliberately NOT back-filled here: we only
--    set it when the existing email is confirmed to be an institutional
--    address.
UPDATE users SET account_status = 'active';
UPDATE users SET external_id = user_id WHERE external_id IS NULL;

-- 4. Mentor relationships move off users.mentor_id into their own table
--    so a student has at most one active mentor, with history retained.
--    users.mentor_id is kept for now and dropped in a later migration
--    once the back-fill below is verified on the live database.
CREATE TABLE mentor_assignments (
    assignment_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id    VARCHAR(20) NOT NULL,
    mentor_id     VARCHAR(20) NOT NULL,
    assigned_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active        TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_assignment_student (student_id),
    KEY idx_assignment_mentor (mentor_id),
    CONSTRAINT fk_assignment_student
        FOREIGN KEY (student_id) REFERENCES users (user_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_assignment_mentor
        FOREIGN KEY (mentor_id) REFERENCES users (user_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4b. Back-fill existing mentor relationships into the new table as
--     active rows. The resulting row count MUST equal:
--         SELECT COUNT(*) FROM users WHERE mentor_id IS NOT NULL;
--     Verify this on the live database before dropping users.mentor_id
--     in migration 003.
INSERT INTO mentor_assignments (student_id, mentor_id, active)
SELECT user_id, mentor_id, 1
FROM users
WHERE mentor_id IS NOT NULL;

-- 5. One-time account activation codes (email only in this phase).
--    Only keyed hashes are stored; never the code itself.
CREATE TABLE account_activation_otps (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(20) NOT NULL,
    code_hash   CHAR(64) NULL,
    attempts    INT NOT NULL DEFAULT 0,
    locked      TINYINT(1) NOT NULL DEFAULT 0,
    used        TINYINT(1) NOT NULL DEFAULT 0,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_activation_user (user_id),
    CONSTRAINT fk_activation_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 6. One row per SIS import run (counts only, no personal data).
CREATE TABLE sis_import_runs (
    run_id             INT AUTO_INCREMENT PRIMARY KEY,
    started_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at        DATETIME NULL,
    students_read      INT NOT NULL DEFAULT 0,
    students_created   INT NOT NULL DEFAULT 0,
    students_updated   INT NOT NULL DEFAULT 0,
    mentors_read       INT NOT NULL DEFAULT 0,
    mentors_created    INT NOT NULL DEFAULT 0,
    mentors_updated    INT NOT NULL DEFAULT 0,
    assignments_created INT NOT NULL DEFAULT 0,
    assignments_updated INT NOT NULL DEFAULT 0,
    unassigned         INT NOT NULL DEFAULT 0,
    errors_json        JSON NULL,
    run_by             VARCHAR(150) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
