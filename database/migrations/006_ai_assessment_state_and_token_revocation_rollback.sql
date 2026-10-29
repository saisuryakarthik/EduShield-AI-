-- =====================================================================
-- EduShield AI -- 006 rollback
--
-- Reverses 006_ai_assessment_state_and_token_revocation.sql.
--
--   * revoked_tokens and ai_assessment_status are dropped. Dropping
--     revoked_tokens means revoked tokens are no longer remembered, so
--     the affected tokens stay valid until they expire on their own.
--   * The UNIQUE key on ai_assessments.request_id is dropped, which
--     restores the previous "many rows per request" behaviour.
--
-- Note: the duplicate assessments removed by the forward migration
-- cannot be restored. Take a backup before rolling back if that
-- history matters.
--
-- The ALTER reversal fails if the index does not exist, so run the
-- information_schema check first if the migration was only partially
-- applied.
-- =====================================================================

-- 3. Drop the one-assessment-per-request constraint.
ALTER TABLE ai_assessments
    DROP INDEX uq_ai_assessment_request;

-- 2. Drop the persistent revocation table.
DROP TABLE IF EXISTS revoked_tokens;

-- 1. Drop the AI assessment state machine.
DROP TABLE IF EXISTS ai_assessment_status;
