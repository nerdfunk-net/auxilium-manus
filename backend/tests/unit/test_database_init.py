"""S11: startup schema sync is serialized by a Postgres advisory lock and the
first-boot CREATE DATABASE race is swallowed."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

import psycopg

from core import database
from core.database import _SCHEMA_SYNC_LOCK_KEY, ensure_database_exists, init_db


class InitDbAdvisoryLockTests(unittest.TestCase):
    def test_locks_before_sync_inside_transaction(self) -> None:
        lock_conn = MagicMock(name="lock_conn")
        begin_ctx = MagicMock(name="begin_ctx")
        begin_ctx.__enter__.return_value = lock_conn
        begin_ctx.__exit__.return_value = False

        manager = MagicMock()
        manager.attach_mock(begin_ctx.__enter__, "enter")
        manager.attach_mock(lock_conn.execute, "execute")

        with (
            patch.object(database, "ensure_database_exists") as ensure_db,
            patch.object(database.engine, "begin", return_value=begin_ctx),
            patch.object(database, "_sync_schema") as sync_schema,
        ):
            manager.attach_mock(sync_schema, "sync_schema")
            init_db()

        ensure_db.assert_called_once_with()

        # The advisory lock statement ran with the shared key...
        self.assertEqual(lock_conn.execute.call_count, 1)
        stmt, params = lock_conn.execute.call_args.args
        self.assertIn("pg_advisory_xact_lock", str(stmt))
        self.assertEqual(params, {"key": _SCHEMA_SYNC_LOCK_KEY})

        # ...before the schema sync, and both inside the begin() context.
        self.assertEqual(
            manager.mock_calls.index(call.execute(stmt, params))
            < manager.mock_calls.index(call.sync_schema()),
            True,
        )
        sync_schema.assert_called_once_with()

    def test_lock_key_fits_signed_32bit(self) -> None:
        self.assertIsInstance(_SCHEMA_SYNC_LOCK_KEY, int)
        self.assertTrue(0 < _SCHEMA_SYNC_LOCK_KEY < 2_147_483_647)


class SyncSchemaLoggingTests(unittest.TestCase):
    def _run_with_results(self, results: dict[str, int]):
        auto = MagicMock()
        auto.run.return_value = results
        with (
            patch("migrations.auto_schema.AutoSchemaMigration", return_value=auto),
            patch.object(database.settings, "apply_safe_migrations", False),
            patch.object(database.settings, "apply_risky_migrations", False),
            self.assertLogs("core.database", level="INFO") as logs,
        ):
            database._sync_schema()
        return logs.output

    def test_logs_summary_when_changes(self) -> None:
        out = self._run_with_results(
            {"tables_created": 1, "columns_added": 2, "indexes_created": 0}
        )
        self.assertTrue(any("Schema sync:" in line for line in out))

    def test_logs_up_to_date_when_no_changes(self) -> None:
        out = self._run_with_results(
            {"tables_created": 0, "columns_added": 0, "indexes_created": 0}
        )
        self.assertTrue(any("up to date" in line for line in out))


class EnsureDatabaseExistsRaceTests(unittest.TestCase):
    def _connect_stub(self, *, create_raises: Exception | None):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = None  # database does not exist yet

        def execute(sql_obj, *args):
            if "CREATE DATABASE" in str(sql_obj) and create_raises is not None:
                raise create_raises

        cursor.execute.side_effect = execute

        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        conn.cursor.return_value = cursor
        return conn

    def test_duplicate_database_is_swallowed(self) -> None:
        conn = self._connect_stub(
            create_raises=psycopg.errors.DuplicateDatabase("already exists")
        )
        with (
            patch("core.database.psycopg.connect", return_value=conn),
            self.assertLogs("core.database", level="INFO") as logs,
        ):
            ensure_database_exists()  # must not raise
        self.assertTrue(any("concurrent starter" in line for line in logs.output))

    def test_other_errors_propagate(self) -> None:
        conn = self._connect_stub(create_raises=RuntimeError("boom"))
        with patch("core.database.psycopg.connect", return_value=conn):
            with self.assertRaises(RuntimeError):
                ensure_database_exists()


if __name__ == "__main__":
    unittest.main()
