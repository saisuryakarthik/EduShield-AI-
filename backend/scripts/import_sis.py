"""
Import students and mentors from SIS CSV exports.

Usage (from the backend/ directory, with the venv active):

    python scripts/import_sis.py
    python scripts/import_sis.py --dry-run
    python scripts/import_sis.py --students path/to/students.csv \
                                 --mentors  path/to/mentors.csv \
                                 --run-by admin@example.edu

Defaults to SIS_IMPORT_DIR. Writes a row to sis_import_runs and prints a
summary. Never prints or stores passwords: imported accounts are created
pending activation.
"""

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from config import DB_CONFIG, SIS_IMPORT_DIR  # noqa: E402
from sis_import import (  # noqa: E402
    MENTOR_COLUMNS,
    STUDENT_COLUMNS,
    import_sis,
    read_csv,
)

import mysql.connector  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Import SIS students and mentors.")
    parser.add_argument(
        "--students",
        default=os.path.join(SIS_IMPORT_DIR, "students.csv"),
        help="Path to students.csv",
    )
    parser.add_argument(
        "--mentors",
        default=os.path.join(SIS_IMPORT_DIR, "mentors.csv"),
        help="Path to mentors.csv",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing anything.",
    )
    parser.add_argument(
        "--run-by",
        default=os.getenv("USERNAME") or os.getenv("USER") or "cli",
        help="Identifier recorded on the import run row.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    students = read_csv(args.students, STUDENT_COLUMNS)
    mentors = read_csv(args.mentors, MENTOR_COLUMNS)

    connection = mysql.connector.connect(**DB_CONFIG)

    try:
        summary = import_sis(
            connection,
            students=students,
            mentors=mentors,
            dry_run=args.dry_run,
            run_by=args.run_by,
        )
    finally:
        connection.close()

    _print_summary(summary, args.dry_run)
    return 0


def _print_summary(summary, dry_run):
    label = "DRY RUN — nothing written" if dry_run else "Import complete"

    print(f"\n=== SIS import: {label} ===")
    print(f"  mentors:  read={summary['mentors_read']} "
          f"created={summary['mentors_created']} "
          f"updated={summary['mentors_updated']}")
    print(f"  students: read={summary['students_read']} "
          f"created={summary['students_created']} "
          f"updated={summary['students_updated']}")
    print(f"  assignments: created={summary['assignments_created']} "
          f"updated={summary['assignments_updated']}")
    print(f"  unassigned students: {summary['unassigned']}")

    if not dry_run:
        print(f"  run_id: {summary['run_id']}")

    for warning in summary["warnings"]:
        print(f"  WARNING row {warning['row']}: {warning['message']}")

    for error in summary["errors"]:
        print(f"  ERROR   row {error['row']}: {error['message']}")

    print(
        f"  totals: {len(summary['errors'])} error(s), "
        f"{len(summary['warnings'])} warning(s)\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
