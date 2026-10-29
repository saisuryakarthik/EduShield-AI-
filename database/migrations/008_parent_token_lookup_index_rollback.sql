-- =====================================================================
-- EduShield AI -- 008 rollback
--
-- Drops the parent-token lookup index added by
-- 008_parent_token_lookup_index.sql. Lookups still work without it, but
-- every parent link resolution falls back to a full table scan.
--
-- Idempotent: safe to run when the index is already absent.
-- =====================================================================

SET @index_exists := (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'phone_change_requests'
      AND INDEX_NAME = 'idx_phone_change_requests_parent_token'
);

SET @ddl := IF(
    @index_exists = 1,
    'ALTER TABLE phone_change_requests
        DROP INDEX idx_phone_change_requests_parent_token',
    'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

DELETE FROM schema_migrations WHERE version = '008';
