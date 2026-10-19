# EduShield AI — Database schema report (Phase 5)

Status: **report only**. No migrations were run and no database was contacted.

Scope: list the tables and columns the backend code (`backend/app.py`)
actually reads or writes, then compare them with the only schema file in
the repository, `database/migrations/001_dual_parent_otp.sql`.

## 1. Tables the code uses

| Table | Read/Write | Created by repo SQL? |
| --- | --- | --- |
| `users` | read + update `phone_number` | pre-existing (base schema not in repo) |
| `phone_change_requests` | read + write | pre-existing; partly altered by 001 |
| `phone_change_otps` | read + write | **yes** (001) |
| `security_context` | read + write | **no** |
| `security_events` | read + write | **no** |
| `audit_logs` | write | **no** |
| `ai_assessments` | read + write | **no** |
| `mentor_reviews` | write | **no** |

## 2. Expected columns

### users
`user_id`, `name`, `email`, `role`, `password_hash`, `phone_number`,
`parent_email`, `parent_phone`, `mentor_id`.

### phone_change_requests
`request_id`, `user_id`, `old_phone`, `new_phone`, `auth_status`,
`parent_verification_status`, `parent_verified_at`, `status`, `mentor_id`,
`parent_token_hash`, `parent_token_expires_at`, `requested_at`,
`reviewed_at`, `rejection_reason`.

Legacy columns no longer written: `otp`, `otp_expires_at`
(migration 001 makes them nullable). `parent_decision` is not referenced.

### phone_change_otps
`otp_id`, `request_id`, `channel`, `code_hash`, `expires_at`, `attempts`,
`max_attempts`, `locked`, `verified`, `verified_at`, `created_at`.

### security_context
`request_id`, `known_device`, `location_deviation`, `failed_login_count`,
`recent_password_reset`, `mfa_verified`, `phone_change_frequency`,
`login_time_deviation`, `trust_score`, `captured_at`.

### security_events
`user_id`, `event_type`, `success`, `device_id`, `ip_address`,
`user_agent`, `latitude`, `longitude`, `created_at`.
Event types used: `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `PASSWORD_RESET`,
`MFA_SUCCESS`.

### audit_logs
`request_id`, `user_id`, `actor`, `action`, `details`.
Action examples: `PHONE_CHANGE_REQUESTED`, `SMS_OTP_SENT`,
`EMAIL_OTP_SENT`, `PARENT_AUTHENTICATION_COMPLETED`,
`AI_ASSESSMENT_GENERATED`, `MENTOR_APPROVED`, `MENTOR_REJECTED`,
`SECURITY_HOLD_RAISED`, `PHONE_CHANGE_CANCELLED`, `OTP_RESENT`.

### ai_assessments
`request_id`, `risk_score`, `risk_level`, `risk_factors`, `model_version`,
`assessed_at`.

### mentor_reviews
`request_id`, `mentor_id`, `decision`, `reason`.

## 3. Gaps in `001_dual_parent_otp.sql`

Migration 001 only:

- adds `users.parent_phone`;
- widens `phone_change_requests.status` and relaxes its legacy
  `otp` / `otp_expires_at` columns;
- creates `phone_change_otps`.

It does **not**:

1. Create `security_context`, `security_events`, `audit_logs`,
   `ai_assessments`, or `mentor_reviews`. The app cannot run without
   them.
2. Add the request-tracking columns the app already expects on
   `phone_change_requests`: `auth_status`, `parent_verification_status`,
   `parent_verified_at`, `parent_token_hash`, `parent_token_expires_at`,
   `requested_at`, `reviewed_at`, `rejection_reason`. (Base schema
   unknown — these may already exist.)
3. Define a foreign key on `security_context`, `ai_assessments`, or
   `mentor_reviews` to `phone_change_requests`.
4. Specify column types for the pre-existing tables.

## 4. Type notes / risks

- `phone_change_otps.request_id` is `VARCHAR(20)`; the FK to
  `phone_change_requests.request_id` requires an identical type. Request
  IDs are generated as `"REQ" + 12 hex chars` (15 chars), so `VARCHAR(20)`
  fits.
- `code_hash` is `CHAR(64)` (SHA-256 hex). Codes are nulled out on verify,
  cancel, and security hold.
- `audit_logs.details` receives `json.dumps(...)`, so it must be a
  text/JSON column.
- No schema file defines `security_context.captured_at` or
  `ai_assessments.assessed_at`, yet both are selected; they must exist as
  `DATETIME` (default `CURRENT_TIMESTAMP`).

## 5. Recommended next step (not done)

Obtain the real base schema (`SHOW CREATE TABLE` for `users` and
`phone_change_requests`) and write a `002_*.sql` that creates the five
missing tables and adds any missing request columns. A backup and a
review against the real types are required before running it.
