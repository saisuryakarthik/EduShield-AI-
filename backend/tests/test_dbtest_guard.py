"""Safety guards for the destructive real-database test harness."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dbtest import (
    DISPOSABLE_DB_ENV,
    TEST_URL_ENV,
    _load_test_config,
    truncate_all,
)


def _url(database):
    return f"mysql://testuser:testpass@127.0.0.1:3306/{database}"


class ConfigGuardTests(unittest.TestCase):

    def _env(self, url=None, designated=None):
        values = {}
        if url is not None:
            values[TEST_URL_ENV] = url
        if designated is not None:
            values[DISPOSABLE_DB_ENV] = designated
        return mock.patch.dict(os.environ, values, clear=True)

    def test_missing_url_skips(self):
        with self._env():
            with self.assertRaises(unittest.SkipTest):
                _load_test_config()

    def test_missing_designated_name_skips(self):
        with self._env(url=_url("edushield_test_isolated")):
            with self.assertRaises(unittest.SkipTest):
                _load_test_config()

    def test_preserved_database_is_rejected(self):
        with self._env(
            url=_url("edushield_test"),
            designated="edushield_test",
        ):
            with self.assertRaises(RuntimeError):
                _load_test_config()

    def test_live_database_is_rejected(self):
        with self._env(
            url=_url("edushieldai"),
            designated="edushieldai",
        ):
            with self.assertRaises(RuntimeError):
                _load_test_config()

    def test_name_must_be_disposable_prefix(self):
        with self._env(
            url=_url("someone_elses_db"),
            designated="someone_elses_db",
        ):
            with self.assertRaises(RuntimeError):
                _load_test_config()

    def test_designated_name_must_match_url(self):
        with self._env(
            url=_url("edushield_test_isolated"),
            designated="edushield_test_other",
        ):
            with self.assertRaises(RuntimeError):
                _load_test_config()

    def test_valid_disposable_database_is_accepted(self):
        with self._env(
            url=_url("edushield_test_isolated"),
            designated="edushield_test_isolated",
        ):
            config = _load_test_config()

        self.assertEqual(config["database"], "edushield_test_isolated")
        self.assertEqual(config["host"], "127.0.0.1")


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(statement)

    def fetchone(self):
        return (self.database,)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, database):
        self.cursor_obj = FakeCursor(database)

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass


class TruncateGuardTests(unittest.TestCase):

    def test_refuses_preserved_database(self):
        connection = FakeConnection("edushield_test")
        env = mock.patch.dict(
            os.environ, {DISPOSABLE_DB_ENV: "edushield_test"}, clear=True
        )

        with env:
            with self.assertRaises(RuntimeError):
                truncate_all(connection)

        self.assertNotIn(
            "SET FOREIGN_KEY_CHECKS = 0", connection.cursor_obj.statements
        )

    def test_refuses_mismatched_database(self):
        connection = FakeConnection("edushield_test_isolated")
        env = mock.patch.dict(
            os.environ,
            {DISPOSABLE_DB_ENV: "edushield_test_other"},
            clear=True,
        )

        with env:
            with self.assertRaises(RuntimeError):
                truncate_all(connection)

        self.assertNotIn(
            "SET FOREIGN_KEY_CHECKS = 0", connection.cursor_obj.statements
        )


if __name__ == "__main__":
    unittest.main()
