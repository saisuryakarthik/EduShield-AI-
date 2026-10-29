-- =====================================================================
-- EduShield AI -- 008: index the parent verification token lookup
--
-- The parent verification page and the parent OTP endpoints resolve a
-- request by phone_change_requests.parent_token_hash. That column had no
-- index, so every parent link and every resend/verify/report call did a
-- full table scan while holding a FOR UPDATE row lock.
--
-- This migration is idempotent: it checks information_schema first so a
-- partial deployment or a re-run cannot fail on a duplicate index.
--
-- Run after 001 and 007. It changes no rows and drops nothing.
-- =====================================================================

SET @index_exists := (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'phone_change_requests'
      AND INDEX_NAME = 'idx_phone_change_requests_parent_token'
);

SET @ddl := IF(
    @index_exists = 0,
    'ALTER TABLE phone_change_requests
        ADD INDEX idx_phone_change_requests_parent_token (parent_token_hash)',
    'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations
    (version, name, checksum, status, applied_at, applied_by, notes)
VALUES
    (
        '008', 'parent_token_lookup_index',
        NULL, 'applied', NOW(), 'manual',
        'Adds idx_phone_change_requests_parent_token (idempotent).'
    )
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    status = VALUES(status),
    verified_at = CURRENT_TIMESTAMP,
    applied_by = VALUES(applied_by),
    notes = VALUES(notes);
