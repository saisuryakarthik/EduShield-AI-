-- =====================================================================
-- EduShield AI — 001: dual parent verification (independent SMS + EMAIL OTP)
--
-- The original schema is NOT in the uploaded project, so the column
-- types here are inferred from the application code. Before running:
--   1. SHOW CREATE TABLE users;
--   2. SHOW CREATE TABLE phone_change_requests;
--   3. Make sure phone_change_requests.request_id matches the type used
--      in phone_change_otps below (the foreign key requires it).
-- Take a backup first.
-- =====================================================================

-- 1. Parent mobile number, needed for the SMS code.
ALTER TABLE users
    ADD COLUMN parent_phone VARCHAR(20) NULL AFTER parent_email;

-- 2. Request status now also takes SECURITY_HOLD and CANCELLED.
--    If status is currently an ENUM, this widens it to VARCHAR.
ALTER TABLE phone_change_requests
    MODIFY status VARCHAR(30) NOT NULL DEFAULT 'PENDING';

-- 3. The old single-OTP columns are no longer written by the app.
--    Making them nullable lets new inserts succeed.
ALTER TABLE phone_change_requests
    MODIFY otp VARCHAR(6) NULL,
    MODIFY otp_expires_at DATETIME NULL;

-- 4. Independent state for each parent code.
--    Only keyed hashes are stored. A code is never stored in plaintext.
CREATE TABLE IF NOT EXISTS phone_change_otps (
    otp_id        INT AUTO_INCREMENT PRIMARY KEY,
    request_id    VARCHAR(20) NOT NULL,
    channel       ENUM('SMS', 'EMAIL') NOT NULL,
    code_hash     CHAR(64) NULL,
    expires_at    DATETIME NOT NULL,
    attempts      INT NOT NULL DEFAULT 0,
    max_attempts  INT NOT NULL DEFAULT 3,
    locked        TINYINT(1) NOT NULL DEFAULT 0,
    verified      TINYINT(1) NOT NULL DEFAULT 0,
    verified_at   DATETIME NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_request_channel (request_id, channel),
    CONSTRAINT fk_phone_change_otps_request
        FOREIGN KEY (request_id)
        REFERENCES phone_change_requests (request_id)
        ON DELETE CASCADE
);

-- 5. Optional cleanup. Run ONLY after the app has been verified.
--    These columns are no longer read or written by the application.
-- ALTER TABLE phone_change_requests DROP COLUMN parent_decision;
-- ALTER TABLE phone_change_requests DROP COLUMN otp;
-- ALTER TABLE phone_change_requests DROP COLUMN otp_expires_at;
