-- =====================================================================
-- EduShield AI — 004 rollback
--
-- Reverses 004_notifications_and_student_delete.sql. Run in this order.
--
-- WARNING: dropping notifications removes all in-app notification
-- history, and dropping deleted_by_student un-hides any request a
-- student had hidden. Neither reverses the underlying data, so take a
-- backup first if that history matters.
-- =====================================================================

-- 1. Remove the soft-delete flag.
ALTER TABLE phone_change_requests
    DROP COLUMN deleted_by_student;

-- 2. Drop the notification inbox.
DROP TABLE IF EXISTS notifications;
