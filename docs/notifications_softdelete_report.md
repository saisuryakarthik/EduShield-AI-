# EduShield AI — Notifications, Soft-Delete & Request-Detail Fix

Implementation report. Real MySQL (`edushield_test` for tests; live DB untouched).
Servers were started only for the live smoke check and stopped afterwards.

## Summary

Four changes delivered:

1. **Fixed the `/request-detail` 500** for requests that have no
   `security_context` / `ai_assessment` yet.
2. **Student soft-delete** of their own requests (hidden from the student's
   list only; mentors and admins still see the record).
3. **"Notify mentor"** from the student dashboard, with per-request limits.
4. **In-app notifications** (migration 004) with a mentor header bell and
   unread badge, plus hooks on parent verification, notify-mentor, security
   hold and cancel-after-notify.

## Files changed

| File | Change |
| --- | --- |
| `frontend-flask/app.py` | Coalesce null `security_context`/`ai_assessment`; add `jsonify` import; add BFF routes `POST /delete-phone-change/<id>`, `POST /notify-mentor/<id>`, `GET /notifications`, `POST /notifications/<id>/read`. |
| `frontend-flask/templates/request-detail.html` | Guard the security-signal grid with `{% if security_context %}` and a fallback notice. |
| `frontend-flask/templates/student-dashboard.html` | Wire Delete + Notify buttons to real endpoints (dialog + fetch). |
| `frontend-flask/templates/mentor-dashboard.html` | Add notification bell, unread badge, inbox panel and JS. |
| `frontend-flask/static/style.css` | Styles for the bell, badge and panel. |
| `backend/app.py` | `create_notification` helper + type constants; soft-delete endpoint; notify-mentor endpoint; `GET /api/notifications`; `POST /api/notifications/<id>/read`; student list filter; hooks in parent-verify, security-hold and cancel. |
| `backend/notifications.py` | In-app message builders + `email_notify_mentor_request`. |
| `database/migrations/004_notifications_and_student_delete.sql` | New migration (see below). |
| `database/migrations/004_notifications_and_student_delete_rollback.sql` | Rollback. |
| `backend/tests/dbtest.py` | Mirror migration 004 (`MIGRATION_004`, column guard, `notifications` in `ALL_TABLES`). |
| `backend/tests/test_notifications.py` | 21 new real-MySQL tests. |

## Migration 004

Applied to `edushield_test` only. Creates `notifications` and adds
`phone_change_requests.deleted_by_student TINYINT(1) NOT NULL DEFAULT 0`.
Full SQL and rollback were shown and approved before use.

## Routes added

Backend (`/api`):

- `POST /api/phone-change-requests/<id>/delete` — student soft-delete.
- `POST /api/phone-change-requests/<id>/notify-mentor` — student nudge.
- `GET /api/notifications` — own inbox + unread count.
- `POST /api/notifications/<id>/read` — mark own notification read.

Frontend BFF:

- `POST /delete-phone-change/<id>`
- `POST /notify-mentor/<id>`
- `GET /notifications`
- `POST /notifications/<id>/read`

## Behaviour

- **Soft delete:** sets `deleted_by_student = 1`. Allowed from PENDING or
  CANCELLED; anything else returns **409**. A request the caller does not own
  returns **404** (never 403). Row is never removed. Audit:
  `REQUEST_DELETED_BY_STUDENT`. Student list filters it out; mentor/admin
  still see it.
- **Notify mentor:** student only, own PENDING request, active assignment
  required. Max **1 per 6 hours** and **3 per request**; beyond either limit
  returns **429** with `Retry-After`. Creates an in-app notification + email
  (name, request id, dashboard link only). Audit: `MENTOR_NOTIFIED`.
- **Notifications:** recipients see only their own rows; marking an unknown or
  foreign id read is **404**. Opening the panel does not mark read; clicking an
  item does. Messages contain no codes, hashes or phone numbers.

## Tests

- `python -m unittest discover -s tests -t .` (from `backend/`, real MySQL):
  **109 passed, 0 failed** (88 before; +21 new). Runtime ~164 s.

## Live smoke check (servers then stopped)

| Check | Result |
| --- | --- |
| `/request-detail` NULL context | 200, shows fallback notice |
| `/request-detail` full context | 200, shows AI panel |
| notify-mentor #1 / #2 | 200 / 429 |
| soft-delete | hidden from student list, still visible to mentor |
| mentor inbox | 1 unread `MENTOR_NOTIFIED`, no secrets in message |
| mark read | unread 0 |
| student reads mentor notification | 404 |

## Unverified

- **Reject decision** path was not re-exercised live in this round (unchanged
  code; covered by the existing mentor-scoping suite).
- **Parent "Resend codes"** was not re-exercised in this round (unchanged
  code).
- Email **delivery** (SMTP) was mocked in tests; only message construction is
  verified. Actual send relies on production SMTP config.
- Notification bell rendering under a real browser was checked only via the
  served HTML containing the bell; no headless browser run this round.
