-- =====================================================================
-- EduShield AI — 002 rollback
--
-- Reverses 002_sis_onboarding.sql. Run in this order.
--
-- WARNING: dropping the tables removes all mentor assignments and
-- activation history. Export them first if that data matters.
--
-- The users.role ENUM can only be narrowed once no admin rows exist,
-- so admins are deleted first. Review this line before running.
-- =====================================================================

DROP TABLE IF EXISTS sis_import_runs;
DROP TABLE IF EXISTS account_activation_otps;
DROP TABLE IF EXISTS mentor_assignments;

-- Required before narrowing the ENUM.
DELETE FROM users WHERE role = 'admin';

ALTER TABLE users
    DROP INDEX uq_users_institutional_email,
    DROP INDEX uq_users_external_id;

ALTER TABLE users
    DROP COLUMN account_status,
    DROP COLUMN year,
    DROP COLUMN section,
    DROP COLUMN department,
    DROP COLUMN external_id,
    DROP COLUMN institutional_email;

ALTER TABLE users
    MODIFY COLUMN role
        ENUM('student', 'mentor') NOT NULL DEFAULT 'student';
