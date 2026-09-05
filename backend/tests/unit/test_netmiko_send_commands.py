"""Tests for NetmikoDeviceSession.send_commands read_timeout/auto_confirm_prompts."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.network.netmiko.connection import NetmikoDeviceSession


def _session() -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1",
        device_type="cisco_ios",
        username="admin",
        password="secret",
    )


class NetmikoSendCommandsTests(unittest.TestCase):
    def test_default_preserves_existing_behavior(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_command.return_value = "Version 15.2"

            result = session.send_commands(["show version"])

        connection.send_command.assert_called_once_with(
            "show version", use_textfsm=False, read_timeout=60
        )
        self.assertTrue(result.success)
        self.assertEqual(result.command_outputs, {"show version": "Version 15.2"})
        self.assertEqual(result.confirmed_prompts, [])

    def test_read_timeout_passed_through(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_command.return_value = "ok"

            session.send_commands(["show version"], read_timeout=120)

        connection.send_command.assert_called_once_with(
            "show version", use_textfsm=False, read_timeout=120
        )

    def test_auto_confirm_prompts_disabled_uses_plain_send_command(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_command.return_value = "ok"

            result = session.send_commands(["show version"], auto_confirm_prompts=False)

        self.assertEqual(result.confirmed_prompts, [])
        connection.write_channel.assert_not_called()

    def test_auto_confirm_prompts_answers_confirmation(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.send_command.return_value = "reload\nProceed with reload? [confirm]"
            connection.read_until_prompt.return_value = "\nLAB#"

            result = session.send_commands(["reload"], auto_confirm_prompts=True)

        connection.write_channel.assert_called_once_with("\n")
        self.assertEqual(result.confirmed_prompts, ["reload"])
        self.assertTrue(result.success)
        self.assertIn("reload", result.command_outputs)

    def test_auto_confirm_prompts_no_cue_leaves_command_unconfirmed(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.send_command.return_value = "show version\nLAB#"

            result = session.send_commands(["show version"], auto_confirm_prompts=True)

        connection.write_channel.assert_not_called()
        connection.read_until_prompt.assert_not_called()
        self.assertEqual(result.confirmed_prompts, [])

    def test_multiple_commands_partial_confirm(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.send_command.side_effect = [
                "show version\nLAB#",
                "reload\nProceed with reload? [confirm]",
            ]
            connection.read_until_prompt.return_value = "\nLAB#"

            result = session.send_commands(
                ["show version", "reload"], auto_confirm_prompts=True
            )

        self.assertEqual(result.confirmed_prompts, ["reload"])
        self.assertIn("show version", result.command_outputs)
        self.assertIn("reload", result.command_outputs)

    def test_use_textfsm_and_auto_confirm_together_raises(self) -> None:
        session = _session()
        with self.assertRaises(ValueError):
            session.send_commands(
                ["show version"], use_textfsm=True, auto_confirm_prompts=True
            )

    def test_exception_mid_loop_returns_partial_outputs(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_command.side_effect = ["Version 15.2", RuntimeError("boom")]

            result = session.send_commands(["show version", "show running-config"])

        self.assertFalse(result.success)
        self.assertEqual(result.command_outputs, {"show version": "Version 15.2"})
        self.assertIn("boom", result.error or "")


if __name__ == "__main__":
    unittest.main()
