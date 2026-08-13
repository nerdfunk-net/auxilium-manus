"""Unit tests for the GET /health/ready status-code table."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.health.ready import build_ready_response


class BuildReadyResponseTests(unittest.TestCase):
    def test_both_ok_returns_200(self) -> None:
        status_code, body = build_ready_response(
            database_ok=True, database_error=None, redis_ok=True, redis_error=None
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(body.status, "ok")
        self.assertTrue(body.database.ok)
        self.assertTrue(body.redis.ok)

    def test_database_down_returns_503(self) -> None:
        status_code, body = build_ready_response(
            database_ok=False,
            database_error="unavailable",
            redis_ok=True,
            redis_error=None,
        )
        self.assertEqual(status_code, 503)
        self.assertEqual(body.status, "unavailable")
        self.assertFalse(body.database.ok)
        self.assertEqual(body.database.error, "unavailable")

    def test_redis_down_returns_503(self) -> None:
        status_code, body = build_ready_response(
            database_ok=True,
            database_error=None,
            redis_ok=False,
            redis_error="unconfigured",
        )
        self.assertEqual(status_code, 503)
        self.assertEqual(body.status, "unavailable")
        self.assertFalse(body.redis.ok)
        self.assertEqual(body.redis.error, "unconfigured")

    def test_both_down_returns_503(self) -> None:
        status_code, body = build_ready_response(
            database_ok=False,
            database_error="unavailable",
            redis_ok=False,
            redis_error="unavailable",
        )
        self.assertEqual(status_code, 503)
        self.assertEqual(body.status, "unavailable")


class PingDatabaseTests(unittest.TestCase):
    def test_ping_database_executes_select_1(self) -> None:
        from core import database as database_module

        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False

        with patch.object(database_module, "SessionLocal", return_value=mock_session):
            database_module.ping_database()

        mock_session.execute.assert_called_once()

    def test_ping_database_propagates_failure(self) -> None:
        from core import database as database_module

        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        mock_session.execute.side_effect = RuntimeError("connection refused")

        with patch.object(database_module, "SessionLocal", return_value=mock_session):
            with self.assertRaises(RuntimeError):
                database_module.ping_database()


if __name__ == "__main__":
    unittest.main()
