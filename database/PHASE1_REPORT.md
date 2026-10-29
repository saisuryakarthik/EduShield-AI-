# EduShield AI — Phase 1 Final Report

**Workstream B: SIS onboarding and admin portal**
Status: **implemented and verified against the live database and the test database.**
Date: 2026-10-20

This report covers the seven checkpoints agreed for Phase 1. It records
what was built, what was verified, the exact database state, and the
items deliberately left open.

---

## 1. Scope

Phase 1 delivered:

* Import students and mentors from SIS CSV files.
* One-time **email** account activation (student and mentor set their own
  password), reusing the dual-parent-OTP security pattern.
* An **admin** role, plus bulk mentor assignment and an admin dashboard.
* Mentor authorisation driven by a real assignment table (not
  `users.mentor_id`), with a mentor only able to see and act on their own
  students.
* The existing dual parent OTP flow kept working throughout.

No SMS is used in this phase (email only, via the existing SMTP). Render
config was not touched. No new dependencies were installed.

---

## 2. Checkpoint summary

| CP | What | Result |
|----|------|--------|
| 1 | Schema plan | Approved by the operator. |
| 2 | Apply migration 002 to live | Applied (9 statements). Back-fill verified: `users.mentor_id IS NOT NULL` = 3 == `mentor_assignments` rows = 3. `SHOW CREATE TABLE` captured for all new/changed tables. Rehearsed on `edushieldai_mig_test`. |
| 3 | SIS import on live | Run 1: 15 students created, 2 mentors created, 14 assignments, 1 unassigned, 1 warning. Run 2: 0 created (idempotent). Verified directly in the DB. |
| 4 | Activation + login on live | Login-before 401; activation code emailed and stored hashed; wrong code 401 with `attempts_left`; correct code activates; post-verify `used=1`, `code_hash=NULL`; login-after 200. |
| 5 | Admin + mentor scoping on live | Summary/users/bulk-assign/unassign all pass; non-admin 403. Mentor scoping: owner 200, non-owner 404 (list, detail and review). Dry-run now supported. |
| 6 | Full test suite on real MySQL | **88/88 pass** against `edushield_test`; in-memory fake DB removed; refuse-to-run guard verified. |
| 7 | Final report | This document. |

---

## 3. Database changes

### Migration 002 — `database/migrations/002_sis_onboarding.sql` (applied to live)

* `users.role` widened to `ENUM('student','mentor','admin')`.
* `users` added: `institutional_email` (UNIQUE), `external_id` (UNIQUE),
  `department`, `section`, `year`, `account_status`
  (`ENUM('pending_activation','active','disabled')`, default
  `pending_activation`).
* Existing rows set to `active`; `external_id` back-filled from
  `user_id`. `institutional_email` deliberately **not** back-filled.
* New table `mentor_assignments` (one active mentor per student, history
  retained) with existing relationships back-filled from
  `users.mentor_id`.
* New table `account_activation_otps` (hashed codes only).
* New table `sis_import_runs` (counts only, no personal data).

Rollback file: `002_sis_onboarding_rollback.sql` (deletes admins before
narrowing the ENUM).

### Base schema in tests

The eight pre-001 tables are not stored in the repository, so
`backend/tests/dbtest.py` contains a faithful copy of the live
`SHOW CREATE TABLE` output. Keep it in sync if the base schema changes.

---

## 4. Application changes

* `backend/sis_import.py` — CSV importer. Idempotent by `external_id`;
  `account_status`/`password_hash` never touched on re-import; blank
  `mentor_id` keeps an existing assignment; unknown mentor is skipped and
  counted unassigned; missing `parent_phone` warns but still imports;
  `dry_run=True` writes nothing. Imported accounts get
  `UNUSABLE_PASSWORD_HASH = "!"` (the column is NOT NULL).
* `backend/scripts/import_sis.py` — CLI (`--students --mentors
  --dry-run --run-by`).
* `backend/scripts/create_admin.py` — one-off admin bootstrap. (Fixed
  during CP5: its INSERT now supplies the NOT NULL `phone_number`.)
* `backend/app.py` — activation routes (`/api/auth/activate/request`,
  `/api/auth/activate/verify`), the `account_status` login gate (403 when
  not active), and admin routes (`/api/admin/summary`,
  `/api/admin/users`, `/api/admin/assignments/bulk`,
  `/api/admin/assignments/unassign`) behind
  `@require_auth(allowed_roles=["admin"])`. Mentor list/detail/review are
  scoped through `mentor_manages_student`; a request a mentor does not
  manage returns **404** (not 403). Bulk assign accepts an optional
  `dry_run`.
* `frontend-flask/` — `/activate`, `/admin-dashboard`, `/admin-users`,
  `/admin-assign` routes and templates (render-verified).

### Activation security (mirrors the parent-OTP pattern)

Keyed HMAC hash with `EDUSHIELD_OTP_PEPPER`; 5-minute expiry; 3 attempts
then lock; one-time use (hash set to NULL after success). Codes are never
returned in API responses, logged, or rendered. Minimum password length
on activation is 8.

---

## 5. Verification and live state

* **Full suite:** 88/88 pass against `edushield_test` (real MySQL).
* **Guard:** pointed at `edushieldai`, the suite errors with `Refusing to
  run tests against database 'edushieldai'`.
* **Live data after CP5** (unchanged by CP6): 22 users, 18 assignments,
  51 `phone_change_requests`, 2 `sis_import_runs`.
* **CP5 live side-effects to review:** new admin row `ADM32430661`;
  `24STUCHH010221` restored to M021 (net unchanged); `24STUCHH011270`
  left with a deactivated (`active = 0`) assignment row where none
  existed before (still counted unassigned); a few `MENTOR_ASSIGNED`
  audit rows.
* Backup before 002:
  `C:\Users\Surya\edushield-backups\edushieldai_pre002_2026-10-19_2209.sql`
  (47,735 bytes).

---

## 6. Test-suite notes

* `TEST_DATABASE_URL` must point at `edushield_test` (set in
  `backend/.env`; the value is not printed here).
* Tests build the schema once, then truncate all tables between tests and
  re-seed. The suite takes ~132s (was ~17s with the fake DB); the cost is
  the price of real-DB fidelity.
* OTP-expiry tests rewind stored timestamps (`shift_time`) because the
  application computes expiry with MySQL `NOW()`.

---

## 7. Open items

### 7.1 Migration 003 — drop `users.mentor_id` (DEFERRED)

`users.mentor_id` is kept for now. It is no longer read anywhere in the
application — a grep confirms the only remaining reference is migration
002's own back-fill `SELECT`. Dropping it is a destructive live change.

**Do not do this yet.** Revisit only after the live system has run for a
while, and then:

1. Take a fresh backup (mysqldump) and record the path.
2. Run a grep confirming nothing reads `users.mentor_id`
   (application, scripts, jobs, SQL).
3. Re-verify the back-fill invariant
   (`users.mentor_id IS NOT NULL` count == active `mentor_assignments`
   count).
4. Write and rehearse `003` plus its rollback on a copy before touching
   live.

### 7.2 Known deviations / decisions

* Test DB collation is `utf8mb4_0900_ai_ci` (not `unicode_ci`): 001
  creates `phone_change_otps` with the DB-default collation, and a
  different collation breaks its FK to `phone_change_requests`
  (errno 3780).
* `test DB` users are seeded with `password_hash = "!"` for pending
  accounts, matching the importer's sentinel.

### 7.3 Carried over from earlier phases

* Rate limiting, CSRF/Origin checks, `secure=True` cookies remain
  outstanding from the Workstream A audit.
* Any model/UI items marked NOT DONE / PARTIAL in `CHANGES.md`.

---

## 8. Constraints honoured

* No `.env` secrets printed; `backend/.env` not deleted.
* No new dependencies installed.
* Parameterised SQL only; server-side role checks.
* No OTP codes or password hashes returned, logged, or rendered.
* No live DB `DROP`/`TRUNCATE` (only `edushield_test`).
* Render config untouched.
