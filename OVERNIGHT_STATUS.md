# EduShieldAI — Overnight Status

Last updated: 2026-10-29 (session complete)

## Initial repository state

- Working tree: `C:\Users\Surya\Downloads\EduShieldAI-dual-otp\EduShieldAI project file`
- Branch HEAD: `381ddd0 Snapshot before dead-code cleanup (Phases 1-5 applied)`
- No commits or pushes were made during this session.
- The working tree already contained a large set of uncommitted changes/untracked
  files from earlier work. These were preserved, not reverted.
- No backend/frontend server was running. Only MySQL was listening (127.0.0.1:3306).
- App database target (read from config without printing credentials):
  host `127.0.0.1`, database `edushieldai`.
- Test database target: `edushield_test` on `127.0.0.1` (from
  `TEST_DATABASE_URL`, value not printed).
- Read-only inspection of `edushield_test`: **3 users, 0 phone-change
  requests** at the start and at the end of this session. `REQ_A` and the E2E
  request rows reported in earlier notes were **not present** at the start of
  this session. They were not deleted by this session and cannot be restored
  from this working tree.

## Baseline verification performed before edits

- `.venv` Python is available; `pytest` is not installed. Tests use `unittest`.
- Non-database baseline:
  `python -m unittest backend.tests.test_no_hardcoded_operational_passwords
  backend.tests.test_demo_inbox_local_only backend.tests.test_otp_delivery_demo -v`
  → **30 passed**.
- Frontend request-detail security-hold suite:
  `python -m unittest frontend-flask.tests.test_request_detail_hold -v`
  → **2 passed**.
- Model load check: artifact loads with scikit-learn **1.9.1**, but was pickled
  with **1.9.0**. `InconsistentVersionWarning` confirmed for `StandardScaler`,
  `LogisticRegression`, and `Pipeline`.
- Docker is not installed, so no disposable MySQL instance was available.

## Task A — Credential exposure containment (done for the safe subset)

Verified present: `backend/seed_user.py` has no hardcoded operational
passwords, requires a non-production `EDUSHIELD_ENV`, requires
`EDUSHIELD_ALLOW_LOCAL_PASSWORD_RESET=1`, requires `--apply`, confirms the user
ID interactively, and reads the new password with `getpass` without printing it.
`.env` was already untracked/ignored; no secrets were printed.

Changes:
- `.gitignore`: restored `!.env.example` (it had been removed, so the tracked
  example file would be ignored on a fresh checkout). Added `*.bak`,
  `*.backup`, `*.sql.gz`, `backups/`.
- Added `backend/tests/test_seed_user_safety.py`.

Commands / results:
- `python -m unittest backend.tests.test_seed_user_safety -v` → **4 passed**.
- `git check-ignore -v --no-index backend/.env.example` → not ignored.
- `git check-ignore -v backend/.env backend/server.log` → ignored.

Not done deliberately: no password rotation, no live credential change, no
deletion of existing logs/backups.

## Task B — Demo delivery and environment safety (verified; no code change needed)

Verified present:
- Demo providers are in-memory only; no SMTP/Twilio/console fallback path.
- `validate_delivery_config()` runs at backend module import.
- Demo inbox routes require authentication, are loopback-only, and refuse
  non-demo mode.
- Provider errors are redacted/bounded before logging.

Commands / results:
- Existing delivery/demo suites: **30 passed** (included above).
- Demo inbox focused suite: **3 passed** (included above).

## Task C — Race conditions (partial: code verified; runtime tests not run)

Verified present:
- Request creation locks the student row `FOR UPDATE` and checks for an open
  request inside the transaction.
- OTP verification locks the parent request row and the specific OTP row
  `FOR UPDATE`, then marks the code one-time-use.
- Parent suspicious-activity reporting locks the request and uses a conditional
  `UPDATE ... WHERE status = 'PENDING'`, checking `rowcount`.
- Mentor review locks the request, re-checks authorization and status, and uses
  the same transaction to change the phone number.
- AI assessment runs only after both OTPs are verified and after the
  verification transaction commits.

Change:
- `backend/app.py`: the "one open request per student" check now includes
  `SECURITY_HOLD` as well as `PENDING`. Before this, a student could open a new
  request while an earlier request was frozen on a security hold.

Limitation: the new condition was **not** exercised against MySQL because the
real-DB harness truncates `edushield_test` (which must be preserved) and no
isolated MySQL instance is available. No concurrency claim is made beyond the
locking strategy above.

## Task D — Database indexes, validation, error handling (done for safe subset)

- No schema change or migration was applied. Existing migrations/indexes were
  not modified.
- Added `GET /api/health/ready` in `backend/app.py`: unauthenticated readiness
  probe that runs `SELECT 1` and returns 200/`ready` or 503/`not_ready` without
  exposing exception text.
- `/api/health` remains a liveness probe that does not touch MySQL.
- `/api/db-test` remains authenticated and returns 404 in production.
- Added `backend/tests/test_health_readiness.py`.

Commands / results:
- `python -m unittest backend.tests.test_health_readiness -v` → **3 passed**
  (ready success, DB failure without leaking the fake error, liveness does not
  call `get_db`).

## Task E — AI assessment integrity and monitoring (done for safe subset)

Verified present:
- AI uses the supported feature vector from `security_context`; trust score is
  excluded.
- AI never approves/rejects; a missing or failed assessment blocks approval.
- Prediction monitoring records the exact feature vector and model version.
- A failed assessment is stored as `FAILED` and can be retried by an admin.

Changes:
- `backend/ai/models/predict.py`: loads features/config first, verifies an
  optional `artifact_sha256` pin before `joblib.load`, and exposes
  `MODEL_VERSION`, `file_sha256`, and `verify_artifact_integrity`.
- `backend/ai/artifacts/config.json`: added `model_version`,
  `trained_sklearn_version: "1.9.0"`, and the SHA-256 of the current artifact.
- `backend/ai/models/train.py`: future training writes the same metadata.
- `backend/app.py`: `MODEL_VERSION` now comes from the artifact config instead
  of a second hardcoded constant.
- Added `backend/tests/test_model_metadata.py`.

Commands / results:
- `python -m unittest backend.tests.test_model_metadata -v` → **4 passed**
  (version exposed, pin matches artifact, changed artifact refused, missing pin
  tolerated for older artifacts).
- `python -m py_compile backend/app.py backend/ai/models/predict.py
  backend/ai/models/train.py frontend-flask/app.py ...` → **compile-ok**.

Unresolved: the artifact still emits `InconsistentVersionWarning` under
scikit-learn 1.9.1. It was not retrained because doing so would change model
behavior without a fresh evaluation/approval. The artifact is trusted local
pickle input; the hash pin detects replacement but does not make untrusted
pickle safe.

## Task F — Remaining feature coverage (not attempted)

Not attempted in this bounded session. Existing modules for SIS import, admin,
reports, recovery, anomaly, timeline, notifications, and exports were inspected
only at a high level and were not re-verified end-to-end. No speculative
features were added.

## Task G — Documentation (done)

- Added `docs/OPERATIONS.md`: local startup, environment variable names,
  database/migration safety, demo delivery, test commands, health checks,
  production WSGI/HTTPS/cookie/proxy/rate-limit requirements, secrets, log
  redaction, backup protection, rotation, and known limitations.
- `frontend-flask/app.py`: corrected the misleading startup banner (it claimed
  `https://0.0.0.0:5002` while serving HTTP) and added an explicit warning that
  the Flask server is not for production.

## Files changed by this session

- `.gitignore`
- `backend/app.py`
- `backend/ai/artifacts/config.json`
- `backend/ai/models/predict.py`
- `backend/ai/models/train.py`
- `frontend-flask/app.py`
- `backend/tests/test_seed_user_safety.py` (new)
- `backend/tests/test_health_readiness.py` (new)
- `backend/tests/test_model_metadata.py` (new)
- `docs/OPERATIONS.md` (new)
- `OVERNIGHT_STATUS.md` (new)

No pre-existing source change was reverted.

## Final test results (actually run)

| Suite | Result |
| --- | --- |
| `test_seed_user_safety` | 4 passed |
| `test_health_readiness` | 3 passed |
| `test_model_metadata` | 4 passed |
| `test_no_hardcoded_operational_passwords` + `test_demo_inbox_local_only` + `test_otp_delivery_demo` | 30 passed |
| `test_otp_flow.SecretHandlingTests` + `AuthStatusRuleTests` + `PhoneNormalisationTests` | 8 passed |
| `frontend-flask.tests.test_request_detail_hold` | 2 passed |

Total focused/non-database tests executed: **51 passed, 0 failed, 0 skipped**.
Failures: none. Warnings: sklearn `InconsistentVersionWarning` (pre-existing) and
a Python regex `SyntaxWarning` during one source-scanning test (pre-existing).

Real-database suites: **not run**. Running them would truncate `edushield_test`
(3 preserved users).

## Database / schema changes

- None. No migration applied, no DDL/DML executed, no database created,
  dropped, truncated, or reset.
- Only read-only `SELECT`/`information_schema` queries were used to confirm
  targets and row counts.

## Git

- HEAD unchanged: `381ddd0`.
- No commit, amend, push, reset, clean, or checkout of user changes.
- Working tree still contains the pre-existing uncommitted work plus the
  changes listed above (74 status entries at the end of the session).
- `git diff --check` reported only line-ending warnings, no whitespace errors.

## Remaining risks / next steps

1. Retrain or re-serialize the model with scikit-learn 1.9.1 and re-run
   `backend/scripts/evaluate_model.py` against a disposable DB before promoting.
2. Run the real-DB and concurrency suites against an isolated MySQL instance
   (not `edushield_test` with preserved data).
3. Confirm/restore `REQ_A` and the E2E records if they are still expected; they
   were already absent at session start.
4. Live-test production SMS/email only with approved provider credentials and a
   non-production recipient.
5. Review the `SECURITY_HOLD` open-request rule and the `/api/health/ready`
   endpoint with the deployment/monitoring owner.
