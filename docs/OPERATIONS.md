# EduShieldAI — Operations and Development Runbook

This document describes what is implemented and verified. It does not invent
production readiness. The Flask development server is **not** a production
server.

## 1. Local development startup

Two Flask processes are used:

| Process | Default URL | Entry point |
| --- | --- | --- |
| Backend API + parent verification page | `http://127.0.0.1:5000` | `backend/app.py` |
| Frontend BFF / UI | `http://127.0.0.1:5002` | `frontend-flask/app.py` |

From the repository root:

```powershell
.\.venv\Scripts\python.exe backend\app.py
.\.venv\Scripts\python.exe frontend-flask\app.py
```

The frontend calls the backend server-to-server. Override the backend URL with
`EDUSHIELD_BACKEND_URL`. Do not run duplicate servers on the same ports.

## 2. Environment variables (names only)

Copy `backend/.env.example` to `backend/.env` and fill it in. Never commit
`backend/.env`.

| Variable | Purpose |
| --- | --- |
| `EDUSHIELD_ENV` | `development`, `test`, or `production`. Controls production-only refusals. |
| `FLASK_DEBUG` | `1` enables Flask debug locally. Keep `0` in production. |
| `EDUSHIELD_HOST`, `EDUSHIELD_PORT` | Backend bind address/port. |
| `EDUSHIELD_BASE_URL` | Public base URL used in parent verification links. |
| `EDUSHIELD_TOKEN_TTL_MINUTES` | JWT lifetime. |
| `EDUSHIELD_ALLOWED_ORIGINS` | Comma-separated browser origins. |
| `EDUSHIELD_COOKIE_SECURE` | `1` sends frontend cookies only over HTTPS. |
| `JWT_SECRET` | JWT signing key. Required. |
| `EDUSHIELD_OTP_PEPPER` | Key for OTP HMACs. Required at startup. |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | MySQL connection. |
| `OTP_DELIVERY_MODE` | `demo` or `production`. Defaults to `demo`. |
| `TWOFACTOR_API_KEY`, `TWOFACTOR_TEMPLATE_NAME` | Production SMS provider. |
| `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` | Production email provider. |
| `SIS_IMPORT_DIR` | Directory for SIS CSV files. |
| `ACTIVATION_*` | Activation OTP expiry, attempts, and resend cooldown. |
| `ADMIN_BOOTSTRAP_EMAIL`, `ADMIN_BOOTSTRAP_PASSWORD` | Used only by `backend/scripts/create_admin.py`. |
| `TEST_DATABASE_URL` | Full `mysql://` URL of a dedicated disposable test database. |
| `EDUSHIELD_TEST_DB_NAME` | Must name exactly the same database as `TEST_DATABASE_URL`; required before any real-DB test can truncate it. The name must start with `edushield_test_`. |

`EDUSHIELD_SMS_PROVIDER` is legacy and ignored by the current delivery layer.

## 3. Database setup and migration safety

- The application targets MySQL via `DB_*`.
- Migrations live in `database/migrations/`. Apply in order:
  `001`, `002`, `004`, `005`, `006`, `007`, `008`.
- `003_drop_users_mentor_id` is intentionally deferred/destructive; do not
  apply it without a separate approved plan.
- Every additive migration has a `*_rollback.sql` companion. Read it before
  applying.
- Back up the target database first. Apply migrations during a maintenance
  window, not with live write traffic.
- The real-DB test harness (`backend/tests/dbtest.py`) **TRUNCATEs every table**
  in the database named by `TEST_DATABASE_URL`. It requires two independent
  opt-ins that must agree: `TEST_DATABASE_URL` and
  `EDUSHIELD_TEST_DB_NAME`. Missing opt-ins skip the suite. It hard-refuses
  `edushield_test` (preserved regression data), `edushieldai` (live app), and
  any name that does not start with `edushield_test_`. It also re-checks the
  connected database immediately before truncating.
- Create a disposable database for tests, for example:
  `CREATE DATABASE edushield_test_isolated CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;`
  then point both variables at it. Never reuse `edushield_test` for destructive
  runs.
- Do not apply an unverified migration to production.

## 4. Demo OTP and notification behavior

- `OTP_DELIVERY_MODE=demo` uses in-memory demo providers for both SMS
  and email. No network call is made. Demo mode is refused at startup when
  `EDUSHIELD_ENV=production`.
- Demo codes are retrievable only from authenticated, loopback-only routes:
  `GET /api/demo/sms-inbox`, `/latest`, and the matching `email-inbox` routes.
  They return HTTP 403 outside demo mode, outside a development/demo/test/local
  environment, or from a non-loopback address.
- `OTP_DELIVERY_MODE=production` selects 2Factor (SMS) and Brevo (email).
  Startup fails if the mode is `production` while `EDUSHIELD_ENV` is a
  development/test value, or if required provider settings are missing.
- There is no SMTP, console, or Twilio fallback. Provider failures propagate as
  `DeliveryError` and never silently switch channel.
- Notification delivery failures after a database commit are logged and do not
  roll back the committed business decision.

## 5. Test commands

Fast, non-database suites (safe to run while preserving test data):

```powershell
.\.venv\Scripts\python.exe -m unittest `
  backend.tests.test_no_hardcoded_operational_passwords `
  backend.tests.test_demo_inbox_local_only `
  backend.tests.test_otp_delivery_demo `
  backend.tests.test_seed_user_safety `
  backend.tests.test_create_admin_safety `
  backend.tests.test_dbtest_guard `
  backend.tests.test_health_readiness `
  backend.tests.test_model_metadata -v

.\.venv\Scripts\python.exe -m unittest `
  backend.tests.test_otp_flow.SecretHandlingTests `
  backend.tests.test_otp_flow.AuthStatusRuleTests `
  backend.tests.test_otp_flow.PhoneNormalisationTests -v

.\.venv\Scripts\python.exe -m unittest `
  frontend-flask.tests.test_request_detail_hold -v
```

Real-database suites (`test_otp_flow`, `test_mentor_scoping`,
`test_ai_failure_isolation`, `test_notifications`, `test_admin`,
`test_activation`, `test_import_sis`, `test_schema_contract`,
`test_token_revocation`) **truncate every table in their target database**.
Use a dedicated disposable database, never `edushield_test` or the live app
database:

```powershell
$env:EDUSHIELD_TEST_DB_NAME = "edushield_test_isolated"
$env:TEST_DATABASE_URL = "mysql://user:pass@127.0.0.1:3306/edushield_test_isolated"
.\.venv\Scripts\python.exe -m unittest `
  backend.tests.test_otp_flow `
  backend.tests.test_mentor_scoping `
  backend.tests.test_ai_failure_isolation `
  backend.tests.test_notifications `
  backend.tests.test_admin `
  backend.tests.test_activation `
  backend.tests.test_import_sis `
  backend.tests.test_schema_contract `
  backend.tests.test_token_revocation -v
```

## 6. Health checks

| Route | Auth | Meaning |
| --- | --- | --- |
| `GET /api/health` | none | Liveness only; does not touch MySQL. |
| `GET /api/health/ready` | none | Readiness; returns 200 when `SELECT 1` succeeds, 503 otherwise. No error detail is exposed. |
| `GET /api/db-test` | JWT | Development/ops diagnostic; returns 404 in production. |

## 7. Production deployment requirements

- Run both applications under a WSGI server (Gunicorn is in the requirements
  files). Do not use `flask run` or `python app.py` in production.
- Terminate TLS at a reverse proxy/load balancer and forward HTTPS only.
- Set `EDUSHIELD_COOKIE_SECURE=1` and `FLASK_DEBUG=0`.
- Set `EDUSHIELD_ENV=production`, a strong `JWT_SECRET` and
  `EDUSHIELD_OTP_PEPPER`, and configure `EDUSHIELD_ALLOWED_ORIGINS`.
- Rate limiting is in-process (`backend/ratelimit.py`) keyed by client IP,
  account, token or request. It is **not shared across workers**; use a shared
  limiter (for example at the proxy) for multi-worker deployments.
- Trusted proxy headers are not automatically trusted. `request.remote_addr`
  is used for rate limiting and the demo-inbox loopback check. If a proxy is
  used, configure it explicitly and add a trusted `ProxyFix` layer only after
  confirming the proxy strips client-supplied forwarding headers.
- Keep MySQL and both applications on private networks; expose only the proxy.

## 8. Secrets, logs, and backups

- Store secrets in the deployment secret manager or an untracked
  `backend/.env`. Never commit them.
- `.gitignore` excludes `.env`, `.env.*` (except `.env.example`), logs,
  backups, and database dumps.
- Application logs must not contain OTPs, parent link tokens, passwords, or
  secret keys. Provider error text is redacted and bounded before logging.
- Do not delete existing logs or backups blindly: they may be needed for an
  incident review. Restrict access and rotate exposed credentials through the
  provider/account owner.
- `backend/seed_user.py` is a local-only password reset helper. It requires a
  non-production `EDUSHIELD_ENV`, `EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET=1`, an
  interactive confirmation, and `--apply`. It never prints the password.
- `backend/scripts/create_admin.py` creates a bootstrap admin. It refuses to
  modify an existing account unless `--update-existing` is passed explicitly.
  It never prints the password.
- Rotate `JWT_SECRET` and `EDUSHIELD_OTP_PEPPER` only with a planned session
  invalidation/OTP reset; rotating the pepper invalidates in-flight OTP hashes.

## 9. Known limitations

- Real SMS/email provider delivery has not been live-tested. Demo mode is the
  only verified delivery path.
- The persisted model was trained with scikit-learn **1.9.0** and the checked
  virtual environment has **1.9.1**. Loading emits
  `InconsistentVersionWarning`. The artifact is now SHA-256 pinned in
  `backend/ai/artifacts/config.json`, and a mismatch refuses to load, but the
  version warning remains until the artifact is retrained.
- Model files are still deserialized with joblib/pickle. Only deploy an
  artifact from a trusted build; the hash pin detects replacement, it does not
  make untrusted pickle safe.
- Concurrency behavior is implemented with InnoDB row locks and conditional
  updates. One MySQL 8.0 row-lock regression test now proves that an approval
  waiting behind a committed `SECURITY_HOLD` observes the hold and is refused
  (`test_hold_committed_while_approval_waits_blocks_the_approval`). This is not
  a general load or multi-worker concurrency certification.
- `edushield_test` was preserved during the verified test run: 3 users,
  0 phone-change requests, 0 OTP rows, 0 audit rows at the end. The disposable
  `edushield_test_isolated` database was used for all destructive suites.
- PDF/CSV exports, recovery, and some dashboards exist in the codebase but
  were not re-verified end-to-end in this run. SIS import, notifications,
  activation, admin assignment, schema contract, mentor scoping and token
  revocation are covered by the real-DB suites above.
