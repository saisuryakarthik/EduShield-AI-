-- =====================================================================
-- EduShield AI -- 007: schema migration ledger
--
-- The project had no migration tracking table, so partial application
-- was invisible: the live database had 006 but was missing 004 and 005.
--
-- This migration creates the ledger and records the state verified by
-- the 2026-10-28 read-only schema audit. It is safe to re-run:
-- CREATE TABLE IF NOT EXISTS plus idempotent inserts.
--
-- Checksums let a future migration runner detect an edited migration
-- after it was applied. NULL means "not captured" (003 was never
-- applied; 007 cannot checksum itself).
-- =====================================================================

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO schema_migrations
    (version, name, checksum, status, applied_at, applied_by, notes)
VALUES
    (
        '001', 'dual_parent_otp',
        '1bbae6b3f357080817d00b93d485da53df12adeaf995f599a848c1d719538e1c',
        'applied', NULL, 'baseline-audit',
        'Verified 2026-10-28; exact original apply time not recorded.'
    ),
    (
        '002', 'sis_onboarding',
        '7b4b75aa8ef0d08543fdb8c675aba691ae3e72415daac53edbbf6d1b242eddfd',
        'applied', NULL, 'baseline-audit',
        'Verified 2026-10-28; exact original apply time not recorded.'
    ),
    (
        '003', 'drop_users_mentor_id',
        NULL, 'deferred', NULL, 'baseline-audit',
        'Intentionally not applied; destructive. See database/PHASE1_REPORT.md.'
    ),
    (
        '004', 'notifications_and_student_delete',
        '6cfb2db71c8c27734b64db8c7bec89347efb3b38e8f635bcda55a310ed9423fd',
        'applied', NOW(), 'schema-audit',
        'Applied 2026-10-28 after backup; was missing from live.'
    ),
    (
        '005', 'security_ops',
        'cfc69638972a6a99c1321b26bf23e43493d7ef7fd3abfd657cbb19c447ce0a70',
        'applied', NOW(), 'schema-audit',
        'Applied 2026-10-28 after backup; was missing from live.'
    ),
    (
        '006', 'ai_assessment_state_and_token_revocation',
        'c65cfe552b4f21e26128caac89580b6fc937abd950974ca65a483d0282c56c77',
        'applied', NULL, 'baseline-audit',
        'Verified 2026-10-28; exact original apply time not recorded.'
    ),
    (
        '007', 'schema_migration_ledger',
        NULL, 'applied', NOW(), 'schema-audit',
        'Creates this ledger. Safe to re-run.'
    )
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    checksum = VALUES(checksum),
    status = VALUES(status),
    verified_at = CURRENT_TIMESTAMP,
    applied_by = VALUES(applied_by),
    notes = VALUES(notes);
