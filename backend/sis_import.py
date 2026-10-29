"""
SIS import: turn students.csv / mentors.csv into EduShield AI accounts.

Design notes
------------
The core (``import_sis``) takes already-parsed rows and a DB connection so
it can be driven from a script or from tests with the in-memory fake DB.
Reading the CSVs is a separate, tiny step (``read_csv``).

Rules that matter:

* Accounts are created with ``account_status='pending_activation'`` and NO
  password. Students and mentors set their own password at activation.
* Re-importing is idempotent: an existing ``external_id`` is updated in
  place, never duplicated. A field is only written (and counted as an
  update) when its value actually changes.
* ``password_hash`` and ``account_status`` are never touched by an import,
  so an account that was already activated stays activated.
* A blank ``mentor_id`` leaves any existing assignment alone. An
  ``mentor_id`` that does not match a known mentor is skipped and counted
  as unassigned.
* ``dry_run=True`` runs every check but writes nothing.
"""

import csv


STUDENT_COLUMNS = [
    "student_id",
    "name",
    "institutional_email",
    "phone",
    "department",
    "section",
    "year",
    "mentor_id",
    "parent_name",
    "parent_phone",
    "parent_email",
]

MENTOR_COLUMNS = [
    "mentor_id",
    "name",
    "institutional_email",
    "department",
]

# users.password_hash is NOT NULL with no default. Imported accounts must
# not have a usable password, so they get a value that can never match any
# password the user might type. Login is additionally gated on
# account_status being 'active'. We do not hash random bytes here because
# it would cost a slow scrypt per row for no benefit.
UNUSABLE_PASSWORD_HASH = "!"


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def read_csv(path, required_columns):
    """
    Read a CSV and return a list of normalised row dicts.

    Headers are matched case-insensitively and whitespace-trimmed. Rows
    are returned as-is (no validation); ``import_sis`` validates.
    """

    rows = []

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)

        header_map = {}
        for original in (reader.fieldnames or []):
            header_map[_clean(original).lower()] = original

        missing = [
            column for column in required_columns
            if column.lower() not in header_map
        ]
        if missing:
            raise ValueError(
                f"{path} is missing required columns: {', '.join(missing)}"
            )

        for raw in reader:
            row = {}
            for column in required_columns:
                row[column] = _clean(raw.get(header_map[column.lower()]))
            rows.append(row)

    return rows


class _Counts:
    def __init__(self):
        self.students_read = 0
        self.students_created = 0
        self.students_updated = 0
        self.mentors_read = 0
        self.mentors_created = 0
        self.mentors_updated = 0
        self.assignments_created = 0
        self.assignments_updated = 0
        self.unassigned = 0
        self.errors = []
        self.warnings = []
        # One entry per source row, in file order. This is what makes a
        # dry run previewable: the admin sees exactly what commit would
        # do, row by row, before anything is written.
        self.rows = []

    def error(self, row, message):
        self.errors.append({"row": row, "message": message})

    def warn(self, row, message):
        self.warnings.append({"row": row, "message": message})

    def plan(self, kind, row, external_id, action, message=None):
        self.rows.append({
            "kind": kind,
            "row": int(row),
            "external_id": external_id,
            "action": action,
            "message": message,
        })

    def as_dict(self):
        return {
            "students_read": self.students_read,
            "students_created": self.students_created,
            "students_updated": self.students_updated,
            "mentors_read": self.mentors_read,
            "mentors_created": self.mentors_created,
            "mentors_updated": self.mentors_updated,
            "assignments_created": self.assignments_created,
            "assignments_updated": self.assignments_updated,
            "unassigned": self.unassigned,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "rows": list(self.rows),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


def _find_by_external_id(cursor, external_id):
    cursor.execute(
        """
        SELECT
            user_id,
            name,
            email,
            institutional_email,
            department,
            section,
            year,
            phone_number,
            parent_email,
            parent_phone,
            role
        FROM users
        WHERE external_id = %s
        """,
        (external_id,)
    )
    return cursor.fetchone()


def _mentor_exists(cursor, external_id):
    cursor.execute(
        "SELECT user_id, role FROM users WHERE external_id = %s",
        (external_id,)
    )
    row = cursor.fetchone()
    return bool(row) and row.get("role") == "mentor"


def _import_mentors(cursor, mentors, counts, dry_run):
    created_ids = set()

    for index, row in enumerate(mentors, start=2):
        counts.mentors_read += 1

        mentor_id = row["mentor_id"]
        name = row["name"]
        institutional_email = row["institutional_email"]
        department = row["department"]

        if not mentor_id or not name or not institutional_email:
            counts.error(
                index,
                "mentor row skipped: mentor_id, name and "
                "institutional_email are required"
            )
            counts.plan(
                "mentor", index, mentor_id or None, "error",
                "mentor_id, name and institutional_email are required"
            )
            continue

        existing = _find_by_external_id(cursor, mentor_id)

        if existing:
            created_ids.add(mentor_id)

        if not existing:
            counts.mentors_created += 1
            created_ids.add(mentor_id)
            counts.plan("mentor", index, mentor_id, "create")
            if not dry_run:
                cursor.execute(
                    """
                    INSERT INTO users
                    (
                        user_id, name, email, institutional_email,
                        external_id, role, department, phone_number,
                        password_hash, account_status
                    )
                    VALUES
                    (%s, %s, %s, %s, %s, 'mentor', %s, '', %s, 'pending_activation')
                    """,
                    (
                        mentor_id, name, institutional_email,
                        institutional_email, mentor_id, department,
                        UNUSABLE_PASSWORD_HASH
                    )
                )
            continue

        changed = (
            _clean(existing["name"]) != name
            or _clean(existing["email"]) != institutional_email
            or _clean(existing["institutional_email"]) != institutional_email
            or _clean(existing["department"]) != department
        )

        if changed:
            counts.mentors_updated += 1
            counts.plan("mentor", index, mentor_id, "update")
            if not dry_run:
                cursor.execute(
                    """
                    UPDATE users
                    SET
                        name = %s,
                        email = %s,
                        institutional_email = %s,
                        department = %s
                    WHERE user_id = %s
                    """,
                    (
                        name, institutional_email, institutional_email,
                        department, existing["user_id"]
                    )
                )

    return created_ids


def _apply_assignment(cursor, student_id, mentor_id, counts, dry_run):
    """Return True when the student ends up with an active mentor."""

    cursor.execute(
        """
        SELECT mentor_id, active
        FROM mentor_assignments
        WHERE student_id = %s
        """,
        (student_id,)
    )
    existing = cursor.fetchone()

    if existing is None:
        counts.assignments_created += 1
        if not dry_run:
            cursor.execute(
                """
                INSERT INTO mentor_assignments
                (student_id, mentor_id, active)
                VALUES (%s, %s, 1)
                """,
                (student_id, mentor_id)
            )
        return True

    if not existing.get("active") or _clean(existing["mentor_id"]) != mentor_id:
        counts.assignments_updated += 1
        if not dry_run:
            cursor.execute(
                """
                UPDATE mentor_assignments
                SET mentor_id = %s, active = 1
                WHERE student_id = %s
                """,
                (mentor_id, student_id)
            )

    return True


def _import_students(cursor, students, counts, dry_run, known_mentor_ids=None):
    if known_mentor_ids is None:
        known_mentor_ids = set()

    for index, row in enumerate(students, start=2):
        counts.students_read += 1

        student_id = row["student_id"]
        name = row["name"]
        institutional_email = row["institutional_email"]
        phone = row["phone"]
        department = row["department"]
        section = row["section"]
        year = row["year"]
        mentor_id = row["mentor_id"]
        parent_email = row["parent_email"]
        parent_phone = row["parent_phone"]

        if not student_id or not name or not institutional_email:
            counts.error(
                index,
                "student row skipped: student_id, name and "
                "institutional_email are required"
            )
            counts.plan(
                "student", index, student_id or None, "error",
                "student_id, name and institutional_email are required"
            )
            continue

        if not parent_phone:
            counts.warn(
                index,
                f"student {student_id}: no parent_phone on file"
            )
            counts.plan(
                "student", index, student_id, "warning",
                "no parent_phone on file"
            )

        existing = _find_by_external_id(cursor, student_id)

        if not existing:
            counts.students_created += 1
            counts.plan("student", index, student_id, "create")
            if not dry_run:
                cursor.execute(
                    """
                    INSERT INTO users
                    (
                        user_id, name, email, institutional_email,
                        external_id, role, department, section, year,
                        phone_number, parent_email, parent_phone,
                        password_hash, account_status
                    )
                    VALUES
                    (%s, %s, %s, %s, %s, 'student', %s, %s, %s,
                     %s, %s, %s, %s, 'pending_activation')
                    """,
                    (
                        student_id, name, institutional_email,
                        institutional_email, student_id, department,
                        section, year, phone, parent_email, parent_phone,
                        UNUSABLE_PASSWORD_HASH
                    )
                )
        else:
            changed = (
                _clean(existing["name"]) != name
                or _clean(existing["email"]) != institutional_email
                or _clean(existing["institutional_email"]) != institutional_email
                or _clean(existing["department"]) != department
                or _clean(existing["section"]) != section
                or _clean(existing["year"]) != year
                or _clean(existing["phone_number"]) != phone
                or _clean(existing["parent_email"]) != parent_email
                or _clean(existing["parent_phone"]) != parent_phone
            )

            if changed:
                counts.students_updated += 1
                counts.plan("student", index, student_id, "update")
                if not dry_run:
                    cursor.execute(
                        """
                        UPDATE users
                        SET
                            name = %s,
                            email = %s,
                            institutional_email = %s,
                            department = %s,
                            section = %s,
                            year = %s,
                            phone_number = %s,
                            parent_email = %s,
                            parent_phone = %s
                        WHERE user_id = %s
                        """,
                        (
                            name, institutional_email, institutional_email,
                            department, section, year, phone, parent_email,
                            parent_phone, existing["user_id"]
                        )
                    )
            else:
                counts.plan("student", index, student_id, "unchanged")

        # ---- mentor assignment ----
        if not mentor_id:
            # Blank mentor_id: keep whatever assignment already exists.
            if existing is None:
                counts.unassigned += 1
            continue

        if mentor_id not in known_mentor_ids and not _mentor_exists(
            cursor, mentor_id
        ):
            counts.unassigned += 1
            counts.warn(
                index,
                f"student {student_id}: mentor {mentor_id} not found, "
                "left unassigned"
            )
            counts.plan(
                "student", index, student_id, "unassigned",
                f"mentor {mentor_id} not found"
            )
            continue

        _apply_assignment(cursor, student_id, mentor_id, counts, dry_run)


def _record_run(cursor, counts, run_by, dry_run):
    if dry_run:
        return None

    import json

    cursor.execute(
        "INSERT INTO sis_import_runs (started_at, run_by) VALUES (NOW(), %s)",
        (run_by,)
    )
    run_id = getattr(cursor, "lastrowid", None) or 0

    cursor.execute(
        """
        UPDATE sis_import_runs
        SET
            finished_at = NOW(),
            students_read = %s,
            students_created = %s,
            students_updated = %s,
            mentors_read = %s,
            mentors_created = %s,
            mentors_updated = %s,
            assignments_created = %s,
            assignments_updated = %s,
            unassigned = %s,
            errors_json = %s
        WHERE run_id = %s
        """,
        (
            counts.students_read,
            counts.students_created,
            counts.students_updated,
            counts.mentors_read,
            counts.mentors_created,
            counts.mentors_updated,
            counts.assignments_created,
            counts.assignments_updated,
            counts.unassigned,
            json.dumps(
                {"errors": counts.errors, "warnings": counts.warnings}
            ),
            run_id,
        )
    )

    return run_id


def import_sis(connection, students, mentors, dry_run=False, run_by=None):
    """
    Import mentors then students. Returns a summary dict with counts and
    ``errors`` / ``warnings`` lists.

    The caller owns the transaction: on success this commits, on any
    unexpected error it rolls back.
    """

    counts = _Counts()
    cursor = connection.cursor(dictionary=True)

    try:
        known_mentor_ids = _import_mentors(cursor, mentors, counts, dry_run)
        _import_students(cursor, students, counts, dry_run, known_mentor_ids)
        run_id = _record_run(cursor, counts, run_by, dry_run)

        if not dry_run:
            connection.commit()

    except Exception:
        if not dry_run:
            connection.rollback()
        raise

    summary = counts.as_dict()
    summary["dry_run"] = dry_run
    summary["run_id"] = run_id
    return summary
