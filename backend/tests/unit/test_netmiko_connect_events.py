"""NetmikoDeviceSession.connect() reports attempts/retries/failures via ``on_event``."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

from services.network.netmiko.connection import (
    NetmikoConnectionError,
    NetmikoDeviceSession,
    RetryPolicy,
)

TARGET = "services.network.netmiko.connection"


class NetmikoConnectEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.session = NetmikoDeviceSession(
            host="10.0.0.1", device_type="cisco_ios", username="admin", password="s3cret-pw"
        )

    def _record(self, kind: str, level: str, message: str) -> None:
        self.events.append((kind, level, message))

    def _kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.events]

    def test_success_on_first_attempt(self) -> None:
        with patch(f"{TARGET}.ConnectHandler"):
            self.session.connect(privileged=False, on_event=self._record)

        self.assertEqual(self._kinds(), ["connect_attempt", "connected"])
        self.assertEqual(self.events[0][1], "info")

    def test_timeouts_then_success_reports_each_attempt_and_retry_delay(self) -> None:
        with patch(f"{TARGET}.ConnectHandler") as handler, patch(f"{TARGET}.time.sleep"):
            handler.side_effect = [
                NetmikoTimeoutException("timed out"),
                NetmikoTimeoutException("timed out"),
                handler.return_value,
            ]
            self.session.connect(
                privileged=False,
                retry=RetryPolicy(backoff_seconds=(10, 20, 30)),
                on_event=self._record,
            )

        self.assertEqual(
            self._kinds(),
            [
                "connect_attempt",
                "connect_retry",
                "connect_attempt",
                "connect_retry",
                "connect_attempt",
                "connected",
            ],
        )
        self.assertIn("attempt 1/4", self.events[0][2])
        retry_event = self.events[1]
        self.assertEqual(retry_event[1], "warning")
        self.assertIn("retrying in 10s", retry_event[2])

    def test_exhausted_retries_end_with_connect_failed_error(self) -> None:
        with patch(f"{TARGET}.ConnectHandler") as handler, patch(f"{TARGET}.time.sleep"):
            handler.side_effect = NetmikoTimeoutException("timed out")
            with self.assertRaises(NetmikoConnectionError):
                self.session.connect(retry=RetryPolicy(backoff_seconds=(1,)), on_event=self._record)

        self.assertEqual(
            self._kinds(),
            ["connect_attempt", "connect_retry", "connect_attempt", "connect_failed"],
        )
        self.assertEqual(self.events[-1][1], "error")
        self.assertIn("2 attempt", self.events[-1][2])

    def test_auth_failure_is_reported_without_leaking_exception_text(self) -> None:
        with patch(f"{TARGET}.ConnectHandler") as handler:
            handler.side_effect = NetmikoAuthenticationException("bad s3cret-pw")
            with self.assertRaises(NetmikoConnectionError):
                self.session.connect(on_event=self._record)

        self.assertEqual(self._kinds(), ["connect_attempt", "auth_failed"])
        for _, _, message in self.events:
            self.assertNotIn("s3cret-pw", message)

    def test_generic_failure_reports_exception_type(self) -> None:
        with patch(f"{TARGET}.ConnectHandler") as handler:
            handler.side_effect = OSError("no route to host")
            with self.assertRaises(NetmikoConnectionError):
                self.session.connect(on_event=self._record)

        self.assertEqual(self._kinds(), ["connect_attempt", "connect_failed"])
        self.assertIn("OSError", self.events[-1][2])

    def test_a_failing_callback_never_breaks_connecting(self) -> None:
        def boom(kind: str, level: str, message: str) -> None:
            raise RuntimeError("event sink down")

        with patch(f"{TARGET}.ConnectHandler"):
            self.session.connect(privileged=False, on_event=boom)  # must not raise

    def test_already_connected_session_emits_nothing(self) -> None:
        with patch(f"{TARGET}.ConnectHandler"):
            self.session.connect(privileged=False)
            self.events.clear()
            self.session.connect(privileged=False, on_event=self._record)

        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
