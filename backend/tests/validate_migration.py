import os
import re
import sys

import mysql.connector
from dotenv import load_dotenv
from urllib.parse import urlparse

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tests"))

load_dotenv(os.path.join(BACKEND, ".env"))

url = urlparse(os.getenv("TEST_DATABASE_URL"))
base = {
    "host": url.hostname,
    "port": url.port,
    "user": url.username,
    "password": url.password,
}

SCRATCH = "edushield_mig_test"


def split_statements(path):
    text = open(path, encoding="utf-8").read()
    lines = [
        line for line in text.splitlines()
        if not line.strip().startswith("--")
    ]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def main():
    root = os.path.dirname(BACKEND)
    migration = os.path.join(
        root, "database", "migrations", "005_security_ops.sql"
    )
    rollback = os.path.join(
        root, "database", "migrations", "005_security_ops_rollback.sql"
    )

    connection = mysql.connector.connect(**base)
    cursor = connection.cursor()
    cursor.execute(f"DROP DATABASE IF EXISTS {SCRATCH}")
    cursor.execute(
        f"CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_0900_ai_ci"
    )
    connection.close()

    import dbtest

    connection = mysql.connector.connect(database=SCRATCH, **base)
    cursor = connection.cursor()

    for statement in (
        dbtest.BASE_SCHEMA
        + dbtest.MIGRATION_001
        + dbtest.MIGRATION_002
        + dbtest.MIGRATION_004
    ):
        cursor.execute(statement)

    for index, statement in enumerate(split_statements(migration)):
        try:
            cursor.execute(statement)
        except Exception as error:
            print(f"MIGRATION FAILED at statement {index}")
            print(statement[:300])
            print(error)
            return 1

    print("migration applied")

    for index, statement in enumerate(split_statements(rollback)):
        try:
            cursor.execute(statement)
        except Exception as error:
            print(f"ROLLBACK FAILED at statement {index}")
            print(statement[:300])
            print(error)
            return 1

    print("rollback applied")

    cursor.execute("SHOW TABLES")
    tables = sorted(row[0] for row in cursor.fetchall())
    print("tables after rollback:", tables)

    connection.close()

    connection = mysql.connector.connect(**base)
    cursor = connection.cursor()
    cursor.execute(f"DROP DATABASE IF EXISTS {SCRATCH}")
    connection.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
