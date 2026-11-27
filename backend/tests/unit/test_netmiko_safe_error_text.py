"""The Netmiko session layer keeps only app-written error text (maintainer decision 2026-11-27).

A driver or library exception can echo a refused config line, a login banner or a credential, and
the steps store ``result.error`` / the ``NetmikoConnectionError`` text as the device message. So the
session layer reduces such an exception to its class name (the full text and traceback go to the
debug log) and keeps the wording it writes itself ("The device rejected ...", the setup-rejection
note) and the text of its own ``NetmikoConnectionError``.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

from services.network.netmiko.connection import (
    NetmikoConnectionError,
    NetmikoDeviceSession,
    safe_error_text,
)

_SECRET = "enable secret hunter2hunter2"
_HANDLER = "services.network.netmiko.connection.ConnectHandler"
_LOGGER = "services.network.netmiko.connection"


def _session() -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1", device_type="cisco_ios", username="admin", password="secret"
    )


class SafeErrorTextTests(unittest.TestCase):
    def test_own_error_keeps_its_text(self) -> None:
        self.assertEqual(safe_error_text(NetmikoConnectionError("Not connected")), "Not connected")

    def test_a_driver_error_is_its_class_name_and_the_text_goes_to_debug(self) -> None:
        with self.assertLogs(_LOGGER, level="DEBUG") as logs:
            self.assertEqual(safe_error_text(RuntimeError(_SECRET)), "RuntimeError")
        self.assertTrue(any(r.levelname == "DEBUG" and r.exc_info for r in logs.records))


class ConnectErrorTests(unittest.TestCase):
    def _connect_error(self, exc: Exception) -> str:
        with patch(_HANDLER, side_effect=exc), self.assertRaises(NetmikoConnectionError) as ctx:
            _session().connect()
        return str(ctx.exception)

    def test_authentication_failure_carries_no_driver_text(self) -> None:
        message = self._connect_error(NetmikoAuthenticationException(_SECRET))
        self.assertEqual(message, "Authentication failed")

    def test_timeout_names_the_class_not_the_text(self) -> None:
        message = self._connect_error(NetmikoTimeoutException(_SECRET))
        self.assertEqual(message, "Connection timeout (NetmikoTimeoutException)")

    def test_other_failure_names_the_class_not_the_text(self) -> None:
        message = self._connect_error(OSError(_SECRET))
        self.assertEqual(message, "Connection failed (OSError)")

    def test_the_live_event_carries_no_driver_text(self) -> None:
        events: list[tuple] = []
        with (
            patch(_HANDLER, side_effect=OSError(_SECRET)),
            self.assertRaises(NetmikoConnectionError),
        ):
            _session().connect(on_event=lambda *args: events.append(args))
        self.assertTrue(events)
        self.assertFalse(any("hunter2" in str(event) for event in events))


class OperationErrorTests(unittest.TestCase):
    """Every result an operation returns or raises after an unexpected driver error."""

    def _connected(self, cls: MagicMock) -> MagicMock:
        connection = cls.return_value
        connection.base_prompt = "R1"
        connection.RETURN = "\n"
        return connection

    def test_send_command(self) -> None:
        with patch(_HANDLER) as cls:
            self._connected(cls).send_command.side_effect = RuntimeError(_SECRET)
            with self.assertRaises(NetmikoConnectionError) as ctx:
                _session().send_command("show version")
        self.assertNotIn("hunter2", str(ctx.exception))
        self.assertIn("RuntimeError", str(ctx.exception))

    def test_send_commands(self) -> None:
        with patch(_HANDLER) as cls:
            self._connected(cls).send_command.side_effect = RuntimeError(_SECRET)
            result = _session().send_commands(["show version"])
        self.assertFalse(result.success)
        self.assertNotIn("hunter2", result.error or "")

    def test_deploy_config(self) -> None:
        with patch(_HANDLER) as cls:
            self._connected(cls).send_config_set.side_effect = RuntimeError(_SECRET)
            result = _session().deploy_config(["interface Gi0/0"], mode="config_mode")
        self.assertFalse(result.success)
        self.assertNotIn("hunter2", result.error or "")

    def test_save_running_config(self) -> None:
        with patch(_HANDLER) as cls:
            self._connected(cls).save_config.side_effect = RuntimeError(_SECRET)
            session = _session()
            session.connect()
            with self.assertRaises(NetmikoConnectionError) as ctx:
                session.save_running_config()
        self.assertNotIn("hunter2", str(ctx.exception))
        self.assertIn("RuntimeError", str(ctx.exception))

    def test_get_configs(self) -> None:
        with patch(_HANDLER) as cls:
            self._connected(cls).send_command.side_effect = RuntimeError(_SECRET)
            result = _session().get_configs(include_running=True, include_startup=False)
        self.assertFalse(result.success)
        self.assertNotIn("hunter2", result.error or "")

    def test_get_configs_with_an_error_after_the_read(self) -> None:
        """Not a ``NetmikoConnectionError``: the generic branch of ``get_configs``."""
        with (
            patch(_HANDLER) as cls,
            patch(
                "services.network.netmiko.connection._strip_running_config_banner",
                side_effect=RuntimeError(_SECRET),
            ),
        ):
            self._connected(cls).send_command.return_value = "hostname R1"
            result = _session().get_configs(include_running=True, include_startup=False)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "RuntimeError")

    def test_upload_file(self) -> None:
        with (
            patch(_HANDLER) as cls,
            patch(
                "services.network.netmiko.connection.file_transfer",
                side_effect=RuntimeError(_SECRET),
            ),
        ):
            self._connected(cls)
            result = _session().upload_file(
                local_path="/tmp/x.bin", dest_file="x.bin", file_system="flash:"
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
