"""A device that rejects Netmiko's session-setup commands (e.g. AAA command authorization of
``terminal length 0``) is reported, and a later command timeout is classified accordingly."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from netmiko.exceptions import ReadTimeout

from services.network.netmiko.connection import (
    NetmikoConnectionError,
    NetmikoDeviceSession,
    setup_rejection_in,
)

TARGET = "services.network.netmiko.connection"

AAA_LOG = (
    b"nxos-1# terminal width 511\r\nnxos-1# terminal length 0\r\n"
    b"% Authorization failed.\r\nnxos-1# "
)


class SetupRejectionScanTests(unittest.TestCase):
    def test_detects_authorization_failure(self) -> None:
        self.assertEqual(
            setup_rejection_in("terminal length 0\n% Authorization failed.\n"),
            "authorization_failed",
        )

    def test_detects_marker_case_insensitively(self) -> None:
        self.assertEqual(
            setup_rejection_in("Command authorization FAILED for user"), "authorization_failed"
        )

    def test_marker_free_policy_mention_is_not_a_rejection(self) -> None:
        self.assertIsNone(setup_rejection_in("Command authorization is required on this device"))

    def test_clean_log_returns_none(self) -> None:
        self.assertIsNone(setup_rejection_in("terminal length 0\nrouter#"))

    def test_empty_log_returns_none(self) -> None:
        self.assertIsNone(setup_rejection_in(""))


class SetupRejectionSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.session = NetmikoDeviceSession(
            host="10.0.0.1", device_type="cisco_nxos", username="admin", password="s3cret-pw"
        )

    def _record(self, kind: str, level: str, message: str) -> None:
        self.events.append((kind, level, message))

    def _connect_with_log(self, log: bytes) -> None:
        def _handler(**kwargs):
            kwargs["session_log"].write(log)
            return MagicMock()

        with patch(f"{TARGET}.ConnectHandler", side_effect=_handler):
            self.session.connect(privileged=False, on_event=self._record)

    def test_rejection_emits_warning_event_without_raw_device_text(self) -> None:
        self._connect_with_log(AAA_LOG)

        kinds = [kind for kind, _, _ in self.events]
        self.assertEqual(kinds, ["connect_attempt", "setup_rejected", "connected"])
        _, level, message = self.events[1]
        self.assertEqual(level, "warning")
        self.assertIn("10.0.0.1", message)
        self.assertNotIn("% Authorization failed", message)

    def test_clean_connect_emits_no_warning(self) -> None:
        self._connect_with_log(b"router# terminal length 0\r\nrouter# ")

        self.assertEqual([k for k, _, _ in self.events], ["connect_attempt", "connected"])

    def test_read_timeout_after_rejection_is_permission_denied(self) -> None:
        self._connect_with_log(AAA_LOG)
        self.session._connection.send_command.side_effect = ReadTimeout("no prompt")

        with self.assertRaises(NetmikoConnectionError) as ctx:
            self.session.send_command("show running-config")

        failure = ctx.exception.failure
        assert failure is not None
        self.assertEqual(failure.kind, "permission_denied")
        self.assertEqual(failure.hint, "check_permissions")
        self.assertFalse(failure.retryable)
        self.assertIn("terminal length 0", str(ctx.exception))

    def test_read_timeout_without_rejection_stays_command_timeout(self) -> None:
        self._connect_with_log(b"router# ")
        self.session._connection.send_command.side_effect = ReadTimeout("no prompt")

        with self.assertRaises(NetmikoConnectionError) as ctx:
            self.session.send_command("show running-config")

        assert ctx.exception.failure is not None
        self.assertEqual(ctx.exception.failure.kind, "command_timeout")

    def test_send_commands_timeout_after_rejection_is_permission_denied(self) -> None:
        self._connect_with_log(AAA_LOG)
        self.session._connection.send_command.side_effect = ReadTimeout("no prompt")

        result = self.session.send_commands(["show running-config"])

        self.assertFalse(result.success)
        assert result.failure is not None
        self.assertEqual(result.failure.kind, "permission_denied")
        self.assertIn("terminal length 0", result.error or "")

    def test_deploy_config_timeout_after_rejection_is_permission_denied(self) -> None:
        self._connect_with_log(AAA_LOG)
        self.session._connection.send_config_set.side_effect = ReadTimeout("no prompt")

        result = self.session.deploy_config(["interface lo0"], mode="config_mode")

        assert result.failure is not None
        self.assertEqual(result.failure.kind, "permission_denied")

    def test_reconnect_ignores_log_from_previous_connect(self) -> None:
        self._connect_with_log(AAA_LOG)
        self.session.disconnect()
        self.events.clear()

        self._connect_with_log(b"router# terminal length 0\r\nrouter# ")

        self.assertEqual([k for k, _, _ in self.events], ["connect_attempt", "connected"])
        self.session._connection.send_command.side_effect = ReadTimeout("no prompt")
        with self.assertRaises(NetmikoConnectionError) as ctx:
            self.session.send_command("show running-config")
        assert ctx.exception.failure is not None
        self.assertEqual(ctx.exception.failure.kind, "command_timeout")


if __name__ == "__main__":
    unittest.main()
