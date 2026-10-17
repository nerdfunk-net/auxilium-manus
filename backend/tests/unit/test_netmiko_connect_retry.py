"""Tests for NetmikoDeviceSession.connect()'s connect-phase retry/backoff."""

from __future__ import annotations

import unittest
from unittest.mock import call, patch

from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

from services.network.netmiko.connection import (
    NetmikoConnectionError,
    NetmikoDeviceSession,
    RetryPolicy,
)


def _session() -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1",
        device_type="cisco_ios",
        username="admin",
        password="secret",
    )


class NetmikoConnectRetryTests(unittest.TestCase):
    def test_no_retry_policy_fails_immediately_on_timeout(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls,
            patch("services.network.netmiko.connection.time.sleep") as sleep_mock,
        ):
            connect_handler_cls.side_effect = NetmikoTimeoutException("timed out")

            with self.assertRaises(NetmikoConnectionError):
                session.connect()

        self.assertEqual(connect_handler_cls.call_count, 1)
        sleep_mock.assert_not_called()

    def test_retries_on_timeout_then_succeeds(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls,
            patch("services.network.netmiko.connection.time.sleep") as sleep_mock,
        ):
            connect_handler_cls.side_effect = [
                NetmikoTimeoutException("timed out"),
                NetmikoTimeoutException("timed out"),
                connect_handler_cls.return_value,
            ]

            session.connect(retry=RetryPolicy(backoff_seconds=(10, 20, 30)))

        self.assertEqual(connect_handler_cls.call_count, 3)
        sleep_mock.assert_has_calls([call(10), call(20)])
        self.assertEqual(sleep_mock.call_count, 2)

    def test_exhausts_retries_then_raises(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls,
            patch("services.network.netmiko.connection.time.sleep") as sleep_mock,
        ):
            connect_handler_cls.side_effect = NetmikoTimeoutException("timed out")

            with self.assertRaises(NetmikoConnectionError):
                session.connect(retry=RetryPolicy(backoff_seconds=(10, 20)))

        self.assertEqual(connect_handler_cls.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_authentication_failure_never_retries(self) -> None:
        session = _session()
        with (
            patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls,
            patch("services.network.netmiko.connection.time.sleep") as sleep_mock,
        ):
            connect_handler_cls.side_effect = NetmikoAuthenticationException("bad creds")

            with self.assertRaises(NetmikoConnectionError):
                session.connect(retry=RetryPolicy(backoff_seconds=(10, 20, 30)))

        self.assertEqual(connect_handler_cls.call_count, 1)
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
