"""Tests for NetmikoDeviceSession.get_running_config()'s banner stripping.

Cisco IOS/IOS-XE prefixes 'show running-config' output with "Building
configuration...\n\nCurrent configuration : <n> bytes\n" -- not valid config
syntax. A device fed this text back via 'configure replace' fails to apply
those two lines and aborts the whole replace (see
workflow_steps/configure_replace_config -- this is what made 'configure
confirm' report nothing pending even though the underlying diff was real).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.network.netmiko.connection import (
    NetmikoDeviceSession,
    _strip_running_config_banner,
)


class StripRunningConfigBannerTests(unittest.TestCase):
    def test_strips_building_and_size_lines(self) -> None:
        raw = (
            "Building configuration...\n"
            "\n"
            "Current configuration : 4246 bytes\n"
            "!\n"
            "version 15.2\n"
            "hostname LAB\n"
        )
        self.assertEqual(
            _strip_running_config_banner(raw),
            "!\nversion 15.2\nhostname LAB",
        )

    def test_size_line_is_case_insensitive_and_spacing_tolerant(self) -> None:
        raw = "building configuration...\ncurrent configuration:123bytes\n!\nhostname LAB\n"
        self.assertEqual(_strip_running_config_banner(raw), "!\nhostname LAB")

    def test_leaves_config_without_banner_untouched(self) -> None:
        raw = "!\nversion 15.2\nhostname LAB"
        self.assertEqual(_strip_running_config_banner(raw), raw)

    def test_does_not_touch_real_comment_lines(self) -> None:
        raw = (
            "Building configuration...\n"
            "\n"
            "Current configuration : 100 bytes\n"
            "!\n"
            "! Last configuration change at 12:00:00 UTC\n"
            "hostname LAB\n"
        )
        result = _strip_running_config_banner(raw)
        self.assertIn("! Last configuration change at 12:00:00 UTC", result)
        self.assertNotIn("Building configuration", result)
        self.assertNotIn("Current configuration", result)


class GetRunningConfigTests(unittest.TestCase):
    def test_get_running_config_strips_banner_from_device_output(self) -> None:
        session = NetmikoDeviceSession(
            host="10.0.0.1", device_type="cisco_ios", username="admin", password="secret"
        )
        session._connection = MagicMock()
        session._connection.send_command.return_value = (
            "Building configuration...\n\nCurrent configuration : 10 bytes\n!\nhostname LAB\n"
        )

        result = session.get_running_config()

        self.assertEqual(result, "!\nhostname LAB")


if __name__ == "__main__":
    unittest.main()
