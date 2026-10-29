# EduShield AI — Change Log (Dual Parent Verification)

This documents the change list applied to the Flask backend and frontend.
Status key: **DONE** (implemented and tested), **PARTIAL**, **NOT DONE**.

## Read this first

1. **Who enters the codes?** The parent enters both codes on a page reached
   from the email link. The student never sees or enters them. This is my
   reading of "Parent receives SMS OTP + Email OTP → provides two-factor
   confirmation". Please confirm.
2. **SMS vs. the earlier "no SMS budget" decision.** Production SMS uses
   2Factor and is not live-tested. The default demonstration mode uses the
   in-app demo inbox for both channels, so no paid SMS/email is sent. Real
   delivery still needs a provider decision and credentials.
3. **OTP expiry is 5 minutes**, as the change list says. The old code used 10.
   The parent link expires after 15 minutes. A resend endpoint exists, with a
   cooldown, and replaces both channel codes together.
4. **The database schema is not in the upload.** The migration uses inferred
   column types. Check them before running it (see Setup).

## What changed

| # | Item | Status | Notes |
|---|------|--------|-------|
| A | Remove parent approval flow | DONE | Approve/deny link, token page, approval email, and the old frontend page are removed. Parent is a verifier only. |
| B | Dual SMS + email OTP | DONE | Two independent codes, one per channel. Hash bound to request and channel. One-time use. |
| C | Backend enforces both | DONE | `auth_status = VERIFIED` only when both channels are verified. Mentor approval returns 403 otherwise. The frontend also disables Approve. |
| D | OTP security | DONE | `secrets`-based codes. Keyed HMAC hashes (`EDUSHIELD_OTP_PEPPER`). 5 min expiry, 3 attempts then lock, one-time use. No codes in API responses, logs, or HTML. **Missing:** rate limiting by IP (see W). |
| E | Real SMS provider | PARTIAL | `demo` provider for local verification; 2Factor production provider not live-tested. Indian numbers need DLT/template registration. No SMTP/console fallback. |
| F | Real email OTP | DONE (demo tested) | `demo` provider in demonstration mode; Brevo production provider when configured. There is no SMTP fallback. Email has branding, student/request context, code, expiry, and a security warning. |
| G | Submit notifications | DONE | Parent gets SMS and email. Mentor gets an email. |
| H | Mentor notified after parent verification | DONE | Email sent once, when both channels complete. |
| I | Decision notifications | DONE | Approve or reject email to student and parent. |
| J | Mentor dashboard states | PARTIAL | Request detail shows SMS and email status per channel and disables Approve until both are verified. The list view and security overview counters are not redesigned. |
| K | AI after verification | DONE | Security context is captured at submission. The AI assessment runs only after both codes are verified. Behaviour change: the mentor sees the AI panel only after verification. |
| L | Model comparison | NOT CHANGED | The code still hard-codes Logistic Regression. See the metrics below. |
| M | AI UI | NOT CHANGED | Existing risk panel kept. |
| N | Database changes | DONE | `001` adds `users.parent_phone`, `phone_change_otps`, and widens `status`. `004`/`005`/`006`/`007` are applied to the development DB. `008` adds the parent-token lookup index and is tested on `edushield_test`; production still needs it applied. |
| O | Audit logging | DONE | Events written: `PHONE_CHANGE_REQUESTED`, `SMS_OTP_SENT`/`SMS_OTP_SEND_FAILED`, `EMAIL_OTP_SENT`/`EMAIL_OTP_SEND_FAILED`, `{SMS,EMAIL}_OTP_{VERIFIED,FAILED,LOCKED}`, `PARENT_AUTHENTICATION_COMPLETED`, `AI_ASSESSMENT_GENERATED`, `MENTOR_{APPROVED,REJECTED}`, `PHONE_NUMBER_UPDATED`, `SECURITY_HOLD_RAISED`, `PHONE_CHANGE_CANCELLED`. **Not logged:** `MENTOR_NOTIFIED`. |
| P | "This wasn't me" | DONE | Parent button puts the request on `SECURITY_HOLD`, locks all codes, and alerts the mentor. Approve is blocked. The mentor can still reject. |
| Q | Student cancellation | DONE | Sets `CANCELLED` and keeps the row for the audit trail. Button on the student dashboard. |
| R | Student UI redesign | NOT DONE | Only copy changes and the cancel button. |
| S | Dual OTP UI | DONE | New parent page with independent SMS and email forms, attempt counters, and the security-hold button. |
| T | Mentor UI redesign | NOT DONE | Only the authentication panel and the approval gate. |
| U | Activity timeline | NOT DONE | Data is in `audit_logs`. No timeline view yet. |
| V | Mobile optimisation | PARTIAL | Parent page is responsive. Other pages were not audited. |
| W | Backend security audit | PARTIAL | Done: parameterised SQL, per-route role checks, server-side gates, debug off by default, login/OTP throttling, frontend origin checks, configurable secure cookies. **Not done:** shared multi-worker rate limiting. |
| X | Deployment | PARTIAL | Demo/development deployment runs over HTTP with the demo delivery provider. Production WSGI/HTTPS and real delivery are not done. |
| Y | Testing | DONE (with caveat) | Real-MySQL suite: 157 passed before the latest delivery/race changes; focused suites after those changes passed (43 OTP-flow, 3 demo-inbox, schema/token/delivery). `dbtest.py` truncates only `edushield_test`. |
| Z | Report | NOT DONE | See the metrics below. |

## P1 fixes (security and integration audit)

Three P1 findings were fixed together. The dual OTP flow, the mentor
authorisation rules, the AI model and the risk thresholds were not changed.

### 1. The AI assessment no longer shares a transaction with the dual OTP

**Before.** The parent verification handler opened one transaction, verified
the two OTPs and then ran the AI assessment inside it. A failing model
raised an exception, the transaction was rolled back, and the verified
request was lost with it. The parent was asked to start over.

**After.** The OTP verification commits first. The AI assessment then runs in
its own transaction and can never undo the verification.

* `ai_assessment_status` (migration 006) is the durable state machine:
  `PENDING` → `COMPLETED` or `PENDING` → `FAILED`.
* The row is written in the same transaction that verifies the last parent
  OTP, so a verified request always carries the fact that an assessment is
  owed.
* `POST /api/admin/ai-assessments/<request_id>/retry` re-runs the
  assessment. It is admin-only, answers 404 for an unknown request, 409 for
  a request that is not verified yet, and 503 when the model still fails.
* A failed assessment writes an audit event (`AI_ASSESSMENT_FAILED`), a
  timeline event and a mentor notification (in-app and email).
* `ai_assessments` now has one row per request (`uq_ai_assessment_request`),
  so a retry updates the assessment instead of piling up duplicates.

### 2. Approval is blocked until the assessment succeeds

**Before.** A request whose assessment failed could still be approved by the
mentor, so an AI failure was indistinguishable from a clean request.

**After.** `review_phone_change_request` refuses to approve a request whose
assessment is not `COMPLETED` (403). The mentor sees the state on the request
detail (`ai_assessment_status`) and can retry from the admin route.

### 3. Token revocation is persistent

**Before.** Revoked token ids were kept in an in-process set. A restart
revived every revoked token, and a multi-worker server only revoked the
token in the worker that handled the logout.

**After.** Revocations live in `revoked_tokens` (migration 006), so they
survive a restart and are shared by every worker.

* Only the token id (`jti`), the owner, the revocation time, the token's own
  expiry and a reason are stored. No token, password or secret.
* `require_auth` reads the store on every request. If the store cannot be
  read the request is refused with 503 rather than being let through.
* `backend/scripts/cleanup_revocations.py` removes rows whose token has
  expired (with a one minute grace period for clock drift). Logout also
  triggers the cleanup opportunistically.

### Migration

`database/migrations/006_ai_assessment_state_and_token_revocation.sql`
(adds `ai_assessment_status` and `revoked_tokens`, and the unique key on
`ai_assessments.request_id`). The rollback file reverses it. **The migration
must be applied before the new backend code is deployed**, otherwise every
authenticated request is refused with 503. It has been applied to the
development database `edushieldai`.

### Tests

`backend/tests/test_ai_failure_isolation.py` (9 tests) and
`backend/tests/test_token_revocation.py` (9 tests) are new. The full suite
was 157 tests before the delivery/race changes, all passing against a real
MySQL database (`cd backend && python -m unittest discover -s tests -t .`).
Focused suites after those changes also pass: 43 OTP-flow tests, 3 demo-inbox
tests, and the delivery/schema/token suites. The full suite takes longer than
180 seconds in this environment; run it with a larger timeout.

## Delivery hardening (demo and production)

* `backend/notifications.py` no longer imports or falls back to SMTP. Demo
  mode always uses the in-app demo provider; production requires
  `BREVO_API_KEY` and `BREVO_SENDER_EMAIL`, and a failure becomes
  `DeliveryError` instead of a silent fallback.
* `backend/otp_delivery.py` validates the selected providers at startup.
  Production mode is refused when `EDUSHIELD_ENV` is demo/development/dev/
  test/testing/local.
* The demo inbox is local-only: all four routes return 403 for non-loopback
  clients or when demo mode is not active.
* `backend/app.py` calls `validate_delivery_config()` at import time so a WSGI
  server cannot start with a broken delivery configuration.

## Race-condition fixes

* Parent verify/resend/report resolve the request through
  `_load_parent_request(..., for_update=True)`, taking a row lock before
  reading or changing verification state.
* Request creation locks the student `users` row inside an explicit
  transaction, so two concurrent submissions cannot both pass the
  one-open-request check.
* The "this wasn't me" update requires `status = 'PENDING'` and checks
  `rowcount`, returning 409 if a concurrent decision already moved the row.

## Small fixes

* `database/migrations/008_parent_token_lookup_index.sql` indexes
  `phone_change_requests.parent_token_hash`; the rollback removes it. Both
  files are idempotent and were tested on `edushield_test`.
* Frontend auth cookies now expire with the 60-minute JWT instead of
  outliving it by seven hours.
* Frontend error pages no longer display raw backend/network exception text;
  details are logged server-side.
* `backend/requirements.txt` pins `scikit-learn==1.9.0`, the version that
  produced the checked-in model artifact, avoiding the pickle version warning
  on a clean install.

## Model results (measured, not invented)

Measured by running `backend/ai/models/train.py` on the 10,000-row dataset
(group-aware split, 2,073 test samples, 736 test users, zero user overlap):

| Metric | Logistic Regression | Random Forest |
|---|---|---|
| Accuracy | 0.8596 | 0.8538 |
| Precision | 0.8215 | 0.7872 |
| Recall | 0.7160 | 0.7432 |
| F1 | 0.7651 | 0.7646 |
| ROC-AUC | 0.9139 | 0.8912 |

Logistic Regression leads on AUC and precision. F1 is effectively tied.
Random Forest has higher recall. The dataset is synthetic, so these numbers
describe the synthetic data, not real fraud. Use them with that caveat.

## Setup

1. Check the schema: `SHOW CREATE TABLE users;` and
   `SHOW CREATE TABLE phone_change_requests;`. Confirm the `request_id` type
   used in the migration matches. Back up the database.
2. Run `database/migrations/001_dual_parent_otp.sql`.
3. Run `database/migrations/006_ai_assessment_state_and_token_revocation.sql`
   before deploying the new backend code. It adds the AI assessment state
   table and the token revocation table. Skipping it makes every
   authenticated request fail with 503.
4. Run `database/migrations/008_parent_token_lookup_index.sql` after `007`.
   It adds the parent-token lookup index and is safe to re-run.
5. Copy `backend/.env.example` to `backend/.env` and fill it in. Generate
   `EDUSHIELD_OTP_PEPPER` and `JWT_SECRET` as long random strings. Keep
   `OTP_DELIVERY_MODE=demo` unless real providers are configured.
6. Set `parent_phone` (and `parent_email`) for each student.
7. Install: `pip install -r backend/requirements.txt`, then
   `pip install -r frontend-flask/requirements.txt`.
8. Run tests only against `edushield_test`; the harness truncates every table
   between tests. Set `TEST_DATABASE_URL` and run from `backend`:
   `python -m unittest discover -s tests -t .`
9. Start the backend (port 5000) and the frontend (port 5002).
10. Schedule the revocation cleanup: `python backend/scripts/cleanup_revocations.py`
    (a daily cron is enough).

## Not included

- Production WSGI/HTTPS serving, real 2Factor/Brevo delivery, and
  multi-worker rate limiting are not implemented.
- The root `README.md` is the Vite template.
- `backend/ai/security/workflow.py` is empty.
