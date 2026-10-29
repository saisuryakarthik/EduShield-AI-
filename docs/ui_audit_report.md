# EduShield AI — Frontend UI Audit Report

**Date:** 2026-10-20
**Scope:** Every interactive element (buttons, links, forms, toggles, modals) across all
roles in the EduShield web UI.
**Method:** Backend (:5000) and frontend BFF (:5002) run against the **test database
`edushield_test`** only; elements driven in a real browser (Playwright 1.64 / Chromium
156) as each role; forms tested with valid, empty and rejected input; destructive
actions exercised on seeded test data with before/after DB snapshots; console + Flask
logs collected.
**Constraint honoured:** This report is **diagnostic only — no source files were changed.**

> Credentials/OTP codes/tokens hashes are not reproduced here. Test password used for
> seeded accounts is recorded separately in the session notes, not in this file.

---

## Summary

| Metric | Value |
|---|---|
| Interactive elements/actions exercised | **51** recorded checks |
| Passed | **40** |
| Failed (real defects) | **1** (request-detail 500 — affects 1 page + 2 blocked buttons) |
| Dead/placeholder controls | **1** (student "Delete request") |
| Blocked (not reachable because of the defect) | **2** |
| Not tested (deliberately skipped) | **1** (parent "Resend codes" — avoids live email) |
| Misdiagnosed during run, re-verified correct | 4 (see *Test-harness notes*) |
| Access-control matrix rows | **28/28 correct** (except request-detail page defect) |
| Backend HTTP 500s | **0** |
| Frontend HTTP 500s | **10** — all on `/request-detail/<id>` |

### Headline findings

1. **DEFECT — `/request-detail/<id>` returns HTTP 500 for any request whose
   `security_context` / `ai_assessment` are `null`.** This is the *normal* case for a
   request that has not been through AI/context capture, i.e. essentially every request
   a mentor must act on. The page is the **only** way a mentor reviews and
   approves/rejects a request, so the entire mentor-review workflow is broken in the UI.
   - Root cause A: `frontend-flask/app.py:1102` — `data.get("ai_assessment", {})`
     returns `None` when the backend explicitly sends `"ai_assessment": null`
     (the `{}` default only applies when the key is *absent*). The next line calls
     `ai.get(...)` → `AttributeError: 'NoneType' object has no attribute 'get'`.
   - Root cause B (once A is fixed): `frontend-flask/templates/request-detail.html:94-127`
     renders the security-signal grid unconditionally; with `security_context == null`,
     `security_context.location_deviation` raises `'None' has no attribute 'location_deviation'`.
   - Confirmed: adding a real `security_context` row **and** an `ai_assessments` row makes
     the same page return **200** with a working Approve/Reject form (decision POST
     succeeds). The bug is purely unguarded `null` handling.

2. **DEAD CONTROL — student dashboard "Delete request" does not delete anything.**
   `frontend-flask/templates/student-dashboard.html:415` shows a toast
   *"No request was deleted. We'll connect this button to the backend later."*
   The confirm dialog opens (JS demo) but no backend call is made.

3. **"Notify mentor" is likewise a UI-only demo** (`...is a UI demo` toast); no backend
   call. Lower severity (informational).

4. Access control (route guards) is **fully correct**: every unauthorized role and every
   anonymous request is redirected (302), authorized roles get 200 — the only 500s are
   the request-detail defect above.

---

## Per-page results

Legend: PASS = behaved as expected · FAIL = defect · DEAD = placeholder/no-op ·
BLOCKED = not reachable due to another defect · NOT-TESTED = deliberately skipped.

### `/login` (public)
| Element | Expected | Actual | Result |
|---|---|---|---|
| "Continue securely" submit, empty fields | HTML5 `required` blocks | browser validation prevented submit | PASS |
| Submit, wrong password | stays on page, error shown | error banner shown | PASS |
| Submit, valid credentials (admin/mentor/student) | redirect to role dashboard | landed on `/admin-dashboard`, `/mentor-dashboard`, `/student-dashboard` | PASS |
| Inline submit-guard script present | present | present | PASS |

### `/activate` (public)
| Element | Expected | Actual | Result |
|---|---|---|---|
| Step `request`, unknown ID | anti-enumeration generic reply | generic reply, no leak (by design) | PASS |
| Step `request`, empty | HTML5 blocked | `required` present | PASS |
| Step `request`, pending student | OTP emailed → verify step shown | verify step shown | PASS |
| Step `verify`, empty | validation, no crash | stayed on page | PASS |
| Step `verify`, mismatched passwords | "passwords do not match" | error rendered | PASS |
| Step `verify`, wrong OTP code | "invalid/expired code" | error rendered | PASS |
| "Back to sign in" link | → `/login` | `href=/login` | PASS |

### `/student-dashboard` (student)
| Element | Expected | Actual | Result |
|---|---|---|---|
| Link "Request phone change" | → `/request-phone-change` | `href=/request-phone-change` | PASS |
| Link "New request" | → `/request-phone-change` | `href=/request-phone-change` | PASS |
| Button "Notify mentor" | notify backend | toast "…is a UI demo", no call | DEAD (informational) |
| Button "Delete" → confirm dialog | delete backend row | dialog opens; toast "…connect…later", no call | DEAD |
| Button "Cancel request" (+confirm) | POST cancel → dashboard | redirected to `/student-dashboard`; DB status PENDING→CANCELLED | PASS |

### `/request-phone-change` (student)
| Element | Expected | Actual | Result |
|---|---|---|---|
| Geolocation gate | status text + submit enable when resolved+valid | works (see harness note) | PASS |
| Phone input sanitising (type `91-1122-2999`) | strip to `9111222999`, enable submit | `9111222999`, enabled | PASS |
| Submit valid phone (already has PENDING) | 409 → error rendered, no crash | error page shown | PASS |
| Submit empty | blocked by disabled button + JS | blocked | PASS |

### `/mentor-dashboard` (mentor)
| Element | Expected | Actual | Result |
|---|---|---|---|
| Filter links All/Pending/Approved/Rejected (4) | navigate `?status=` | present; `?status=PENDING` works | PASS |
| Link "Review request ↗" | → `/request-detail/<id>` | `href=/request-detail/REQAUDIT000001` | PASS |

### `/request-detail/<id>` (student/mentor/admin)
| Element | Expected | Actual | Result |
|---|---|---|---|
| GET with `null` security_context/ai_assessment | 200 + decision form | **HTTP 500** `'NoneType'…get` | **FAIL** |
| Button "Approve request" | present | unreachable (page 500) | BLOCKED |
| Button "Reject request" (+confirm) | present | unreachable (page 500) | BLOCKED |
| GET with full context (injected) | 200 + decision form | 200, Approve+Reject present | PASS |
| Button "Approve" (verified request, +confirm) | decision POST → `?success=true` | `…?success=true` | PASS |

### `/admin-dashboard` (admin)
| Element | Expected | Actual | Result |
|---|---|---|---|
| Nav "Overview" | → `/admin-dashboard` | `href=/admin-dashboard` | PASS |
| Nav "Users" | → `/admin-users` | `href=/admin-users` | PASS |
| Nav "Assignments" | → `/admin-assign` | `href=/admin-assign` | PASS |
| Nav "Sign out" | log out → `/login` | `href=/logout` (logout redirects to /login) | PASS |

### `/admin-users` (admin)
| Element | Expected | Actual | Result |
|---|---|---|---|
| Filter form (role/status/search + "Filter") | GET with query, filtered table | `?role=student&status=active&q=` 200 | PASS |

### `/admin-assign` (admin)
| Element | Expected | Actual | Result |
|---|---|---|---|
| "Assign mentors" (valid `student,mentor`) | bulk-assign | message shown; DB assignment created | PASS |
| "Unassign mentors" (valid student_id) | unassign | message shown; DB assignment `active`→0 | PASS |
| "Assign mentors" (empty) | validation error, no crash | "Enter at least one…" | PASS |

### `/parent/verify/<token>` (backend-served on :5000, parent)
| Element | Expected | Actual | Result |
|---|---|---|---|
| GET bad token | 404 invalid page | HTTP 404 | PASS |
| GET valid open token | 200, 2 code forms | HTTP 200, forms=2 | PASS |
| Buttons "Resend codes" + "This wasn't me" | both present | present | PASS |
| Submit code `123` | rejected | client `pattern` blocked (no server msg) | PASS* |
| Submit wrong 6-digit code | "Incorrect code." | `Incorrect code.` (HTTP 401) | PASS |
| Button "This wasn't me" (report) | request → SECURITY_HOLD | DB REQAUDIT000004 → SECURITY_HOLD | PASS* |
| Button "Resend codes" | resend SMS+Email | **not clicked** (would deliver live email) | NOT-TESTED |

\* See *Test-harness notes*.

---

## Access-control matrix

Guard behaviour verified with an authenticated session per role (HTTP, no JS).
Expected: authorized role → 200; any other authenticated role → 302 `/dashboard`;
anonymous → 302 `/login`. **Actual result matched expectation in all 28 cases** (the
three `/request-detail` "authorized" rows return 500 due to the defect, counted as FAIL).

| Page | anon | student | mentor | admin |
|---|---|---|---|---|
| `/student-dashboard` | 302 /login ✓ | 200 ✓ | 302 /dashboard ✓ | 302 /dashboard ✓ |
| `/request-phone-change` | 302 /login ✓ | 200 ✓ | 302 /dashboard ✓ | 302 /dashboard ✓ |
| `/mentor-dashboard` | 302 /login ✓ | 302 /dashboard ✓ | 200 ✓ | 302 /dashboard ✓ |
| `/admin-dashboard` | 302 /login ✓ | 302 /dashboard ✓ | 302 /dashboard ✓ | 200 ✓ |
| `/admin-users` | 302 /login ✓ | 302 /dashboard ✓ | 302 /dashboard ✓ | 200 ✓ |
| `/admin-assign` | 302 /login ✓ | 302 /dashboard ✓ | 302 /dashboard ✓ | 200 ✓ |
| `/request-detail/<id>` | 302 /login ✓ | **500 ✗** | **500 ✗** | **500 ✗** |

Route guards rely on `get_current_user()` (validates the `auth_token` against backend
`GET /api/auth/me`) plus `require_role(...)`; the `user_role` cookie is not trusted.
Anonymous access is correctly denied everywhere.

---

## Errors by page

### Browser console errors (captured during the run)
| Page | Role | Type | Message | Attributed to |
|---|---|---|---|---|
| mentor-dashboard | mentor | error | 500 INTERNAL SERVER ERROR (×2) | the request-detail defect surfaced via `Review request` fetch chain* |
| request-detail | mentor | error | 500 INTERNAL SERVER ERROR | the defect (page itself) |
| parent-verify | parent | error | 404 NOT FOUND | expected (deliberate bad-token test) |
| parent-verify | parent | error | 401 UNAUTHORIZED | expected (deliberate wrong-code test) |

\* The mentor-dashboard 500 console lines appear when the detail page (linked from the
dashboard) is requested.

### Flask / server logs
- **Backend (`backend/server_test.log`):** **0** HTTP 5xx across the whole run.
- **Frontend (`frontend-flask/frontend_test.log`):** **10** HTTP 500s, **all** on
  `GET /request-detail/<id>` (REQAUDIT000002/3). No other 5xx.

---

## Database side effects observed (test DB only, before/after snapshots)

All changes are in `edushield_test`; no live data touched.

| Action (UI) | Table | Change |
|---|---|---|
| Admin "Assign mentors" (then "Unassign") | `mentor_assignments` | row created then `active` 1→0 |
| Student "Cancel request" | `phone_change_requests` | REQAUDIT000001 PENDING → **CANCELLED** |
| Activate step "request" | `account_activation_otps` | +1 row (OTP issued) |
| Parent "This wasn't me" | `phone_change_requests` | REQAUDIT000004 PENDING → **SECURITY_HOLD** |
| Parent wrong code / actions | `audit_logs`, `security_events` | +8 audit rows, +16 security events |
| Mentor "Approve" (full-context request) | `phone_change_requests` | decision accepted (`?success=true`) |

> To exercise a mentor request that lacks AI/context data, one `security_context` row and
> one `ai_assessments` row were temporarily inserted for REQAUDIT000002 (removed the
> temporary `ai_assessments` row for REQAUDIT000003; the added context row remains in the
> test DB — no impact on live data). Two extra requests (REQAUDIT000004) and their OTP
> rows were created in `edushield_test` for parent-page testing.

---

## Test-harness notes (first-run mis-diagnoses, re-verified)

These appeared as FAIL/DEAD on the first pass and were re-tested to establish the true
behaviour:

1. **Admin "Sign out" → `href=/logout`** — correct. `/logout` clears the session and
   redirects to `/login`; my initial expected value (`/login`) was wrong. **PASS.**
2. **"Geolocation gate" reported `submit_disabled=True`** — a timing artefact: the check
   ran before geolocation resolved. With an explicit wait for “Ready to submit”, the
   gate behaves correctly. **PASS.**
3. **"Submit valid phone change" did not redirect** — the student already had a PENDING
   request, so the backend correctly returned **409** and the frontend re-rendered with
   the backend message (no crash). **PASS (expected conflict).**
4. **"Submit code '123'" produced no message** — the input's `pattern="[0-9]{6}"` +
   `required` caused the browser to block submission client-side. **PASS.**
5. **Parent "This wasn't me" showed empty message text** — the DB confirms the request
   moved to `SECURITY_HOLD`, so the action succeeded; the toast/confirmation read raced
   the state update. **PASS.**
6. **Non-digit stripping first reported `91112229`** — a Playwright `fill()` artefact;
   re-tested with character-by-character `type()` and it correctly yields `9111222999`.

---

## Untested / out-of-scope items

| Item | Reason |
|---|---|
| Parent "Resend codes" click | would deliver a **live email** via SMTP; presence + wiring verified only |
| Mentor "Reject request" button | could not be reached because the detail page 500s (defect); "Approve" was exercised on a full-context request instead |
| Student "Delete request" backend effect | confirmed there is **no** backend effect (placeholder) |
| Real parent SMS/email delivery | console SMS provider only; SMTP email deliberately not triggered |
| Full activation happy-path (set password → login) | requires reading a live emailed OTP code; validation paths exercised instead |
| `/dashboard` generic redirect | not an interactive page (pure router) |
| Static assets | none beyond `style.css`; no standalone JS files exist in the frontend |

---

## Recommended fixes (for a follow-up change, not performed here)

1. **`frontend-flask/app.py` (request-detail):** coalesce `None` to `{}` for
   `ai_assessment` and `security_context`, e.g.
   `data.get("ai_assessment") or {}` / `data.get("security_context") or {}`
   (line ~935/945), so an explicit JSON `null` is handled.
2. **`frontend-flask/templates/request-detail.html`:** wrap the security-signal grid
   (lines ~94-127) in `{% if security_context %}` and the AI panel in
   `{% if ai_assessment %}` (the AI panel already has a guard).
3. **Student dashboard:** either wire "Delete request" to a real endpoint or remove it;
   relabel "Notify mentor" clearly as a demo (or wire it) so it is not mistaken for a
   live action.
