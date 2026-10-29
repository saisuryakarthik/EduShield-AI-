-- =====================================================================
-- EduShield AI — 005 rollback
--
-- Reverses 005_security_ops.sql. Dropping the tables removes the new
-- data; the two ALTERs are reverted by dropping the added columns.
--
-- Take a backup first. The ALTER reversals fail if the column does
-- not exist, so run the "information_schema" check first if the
-- migration was only partially applied.
-- =====================================================================

-- 10. Drop the notification delivery bookkeeping columns.
ALTER TABLE notifications
    DROP COLUMN delivery_status,
    DROP COLUMN delivery_channel,
    DROP COLUMN delivery_error,
    DROP COLUMN delivered_at;

-- 11. Drop the sis_import_runs -> sis_import_reports link.
ALTER TABLE sis_import_runs
    DROP COLUMN report_id;

-- 9. SLA policies.
DROP TABLE IF EXISTS request_sla_policies;

-- 8. Notification delivery attempts.
DROP TABLE IF EXISTS notification_deliveries;

-- 7. Import reports.
DROP TABLE IF EXISTS sis_import_reports;

-- 6. Emergency account recovery.
DROP TABLE IF EXISTS account_recoveries;

-- 5. Request timeline.
DROP TABLE IF EXISTS request_timeline;

-- 4. Security alerts.
DROP TABLE IF EXISTS security_alerts;

-- 3. Model prediction monitoring.
DROP TABLE IF EXISTS model_predictions;

-- 2. Model evaluations.
DROP TABLE IF EXISTS model_evaluations;

-- 1. Model registry.
DROP TABLE IF EXISTS model_registry;
