# EduShield AI — Change Log (Dual Parent Verification)

This documents the change list applied to the Flask backend and frontend.
Status key: **DONE** (implemented and tested), **PARTIAL**, **NOT DONE**.

## Read this first

1. **Who enters the codes?** The parent enters both codes on a page reached
   from the email link. The student never sees or enters them. This is my
   reading of "Parent receives SMS OTP + Email OTP → provides two-factor
   confirmation". Please confirm.
2. **SMS vs. the earlier "no SMS budget" decision.** Your saved note says
   email-only because there is no budget for SMS. The change list requires an
   SMS provider. The SMS code is required, so **if SMS is disabled, no request
   can ever be completed.** Decide before deployment.
3. **OTP expiry is 5 minutes**, as the change list says. The old code used 10.
   The parent link expires after 15 minutes. There is no resend, so a parent
   who misses the window has to be sent a new request.
4. **The database schema is not in the upload.** The migration uses inferred
   column types. Check them before running it (see Setup).

## What changed

| # | Item | Status | Notes |
|---|------|--------|-------|
| A | Remove parent approval flow | DONE | Approve/deny link, token page, approval email, and the old frontend page are removed. Parent is a verifier only. |
| B | Dual SMS + email OTP | DONE | Two independent codes, one per channel. Hash bound to request and channel. One-time use. |
| C | Backend enforces both | DONE | `auth_status = VERIFIED` only when both channels are verified. Mentor approval returns 403 otherwise. The frontend also disables Approve. |
| D | OTP security | DONE | `secrets`-based codes. Keyed HMAC hashes (`EDUSHIELD_OTP_PEPPER`). 5 min expiry, 3 attempts then lock, one-time use. No codes in API responses, logs, or HTML. **Missing:** rate limiting by IP (see W). |
| E | Real SMS provider | PARTIAL | Twilio REST integration behind `send_sms()`. Not tested against live Twilio. Indian numbers need DLT registration. The `console` provider is dev-only and refuses to run in production. |
| F | Real email OTP | DONE | Uses the existing SMTP settings. Email has branding, student and request context, the code, expiry, and a security warning. |
| G | Submit notifications | DONE | Parent gets SMS and email. Mentor gets an email. |
| H | Mentor notified after parent verification | DONE | Email sent once, when both channels complete. |
| I | Decision notifications | DONE | Approve or reject email to student and parent. |
| J | Mentor dashboard states | PARTIAL | Request detail shows SMS and email status per channel and disables Approve until both are verified. The list view and security overview counters are not redesigned. |
| K | AI after verification | DONE | Security context is captured at submission. The AI assessment runs only after both codes are verified. Behaviour change: the mentor sees the AI panel only after verification. |
| L | Model comparison | NOT CHANGED | The code still hard-codes Logistic Regression. See the metrics below. |
| M | AI UI | NOT CHANGED | Existing risk panel kept. |
| N | Database changes | DONE (migration written, not run) | `database/migrations/001_dual_parent_otp.sql`. Adds `users.parent_phone`, the `phone_change_otps` table, and widens `status`. |
| O | Audit logging | DONE | Events written: `PHONE_CHANGE_REQUESTED`, `SMS_OTP_SENT`/`SMS_OTP_SEND_FAILED`, `EMAIL_OTP_SENT`/`EMAIL_OTP_SEND_FAILED`, `{SMS,EMAIL}_OTP_{VERIFIED,FAILED,LOCKED}`, `PARENT_AUTHENTICATION_COMPLETED`, `AI_ASSESSMENT_GENERATED`, `MENTOR_{APPROVED,REJECTED}`, `PHONE_NUMBER_UPDATED`, `SECURITY_HOLD_RAISED`, `PHONE_CHANGE_CANCELLED`. **Not logged:** `MENTOR_NOTIFIED`. |
| P | "This wasn't me" | DONE | Parent button puts the request on `SECURITY_HOLD`, locks all codes, and alerts the mentor. Approve is blocked. The mentor can still reject. |
| Q | Student cancellation | DONE | Sets `CANCELLED` and keeps the row for the audit trail. Button on the student dashboard. |
| R | Student UI redesign | NOT DONE | Only copy changes and the cancel button. |
| S | Dual OTP UI | DONE | New parent page with independent SMS and email forms, attempt counters, and the security-hold button. |
| T | Mentor UI redesign | NOT DONE | Only the authentication panel and the approval gate. |
| U | Activity timeline | NOT DONE | Data is in `audit_logs`. No timeline view yet. |
| V | Mobile optimisation | PARTIAL | Parent page is responsive. Other pages were not audited. |
| W | Backend security audit | PARTIAL | Done: parameterised SQL throughout, role checks on each route, server-side gates, debug off by default. **Not done:** rate limiting, CSRF tokens, `secure=True` on cookies. |
| X | Deployment | NOT DONE | `backend/.env.example` added. No production WSGI or HTTPS setup. |
| Y | Testing | DONE (with caveat) | 35 tests in `backend/tests/`. They run the real routes against an in-memory fake database, not MySQL. |
| Z | Report | NOT DONE | See the metrics below. |

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
3. Copy `backend/.env.example` to `backend/.env` and fill it in. Generate
   `EDUSHIELD_OTP_PEPPER` and `JWT_SECRET` as long random strings.
4. Set `parent_phone` (and `parent_email`) for each student.
5. Install: `pip install -r backend/requirements.txt`, then
   `pip install -r frontend-flask/requirements.txt`.
6. Run tests: `cd backend && python -m unittest discover -s tests -t .`
7. Start the backend (port 5000) and the frontend (port 5002).

## Not included

- `app.py` at the project root is an older, diverged copy of
  `frontend-flask/app.py`. It is untouched and should be deleted.
- `backend/ai/security/workflow.py` is empty.
- The root `README.md` is the Vite template.
