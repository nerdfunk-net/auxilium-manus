"""Tests for NetmikoDeviceSession.deploy_config session-log/read_timeout behaviour."""

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


class NetmikoDeployConfigTests(unittest.TestCase):
    def test_read_timeout_passed_to_send_config_set(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_config_set.return_value = "ok"
            result = session.deploy_config(
                ["no username bob"], mode="config_mode", read_timeout=120
            )

        connection.send_config_set.assert_called_once_with(["no username bob"], read_timeout=120)
        self.assertTrue(result.success)
        self.assertIsNone(result.session_log)

    def test_failure_captures_session_log(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value

            def _fake_read(*args, **kwargs):
                buffer = session._session_log_buffer
                if buffer is not None:
                    buffer.write(b"LAB(config-if)#")
                raise RuntimeError("Pattern not detected")

            connection.send_config_set.side_effect = _fake_read

            result = session.deploy_config(["interface Gi0/0"], mode="config_mode")

        self.assertFalse(result.success)
        self.assertIn("Pattern not detected", result.error or "")
        self.assertEqual(result.session_log, "LAB(config-if)#")

    def test_session_log_disabled_yields_none(self) -> None:
        session = NetmikoDeviceSession(
            host="10.0.0.1",
            device_type="cisco_ios",
            username="admin",
            password="secret",
            capture_session_log=False,
        )
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_config_set.side_effect = RuntimeError("boom")

            result = session.deploy_config(["no username bob"], mode="config_mode")

        self.assertFalse(result.success)
        self.assertIsNone(result.session_log)
        call_kwargs = connect_handler_cls.call_args.kwargs
        self.assertIsNone(call_kwargs["session_log"])

    def test_auto_confirm_prompts_disabled_uses_send_config_set(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.send_config_set.return_value = "ok"
            result = session.deploy_config(
                ["no username kannweg"], mode="config_mode", auto_confirm_prompts=False
            )

        connection.send_config_set.assert_called_once()
        connection.config_mode.assert_not_called()
        self.assertTrue(result.success)
        self.assertEqual(result.confirmed_prompts, [])

    def test_auto_confirm_prompts_answers_confirmation(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.config_mode.return_value = "LAB(config)#"
            connection.exit_config_mode.return_value = "LAB#"
            connection.send_command.return_value = (
                "no username kannweg privilege 15 secret 9 xyz\n"
                "This operation will remove all username related configurations "
                "with same name.Do you want to continue? [confirm]"
            )
            connection.read_until_prompt.return_value = "\nLAB(config)#"

            result = session.deploy_config(
                ["no username kannweg privilege 15 secret 9 xyz"],
                mode="config_mode",
                auto_confirm_prompts=True,
            )

        connection.send_config_set.assert_not_called()
        connection.config_mode.assert_called_once()
        connection.write_channel.assert_called_once_with("\n")
        connection.exit_config_mode.assert_called_once()
        self.assertTrue(result.success)
        self.assertEqual(
            result.confirmed_prompts,
            ["no username kannweg privilege 15 secret 9 xyz"],
        )

    def test_auto_confirm_prompts_no_cue_leaves_command_unconfirmed(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.config_mode.return_value = "LAB(config)#"
            connection.exit_config_mode.return_value = "LAB#"
            connection.send_command.return_value = "interface Gi0/0\nLAB(config-if)#"

            result = session.deploy_config(
                ["interface Gi0/0"], mode="config_mode", auto_confirm_prompts=True
            )

        connection.write_channel.assert_not_called()
        connection.read_until_prompt.assert_not_called()
        self.assertTrue(result.success)
        self.assertEqual(result.confirmed_prompts, [])

    def test_auto_confirm_prompts_exec_mode(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.send_command.return_value = "reload\nProceed with reload? [confirm]"
            connection.read_until_prompt.return_value = "\nLAB#"

            result = session.deploy_config(["reload"], mode="exec_mode", auto_confirm_prompts=True)

        connection.write_channel.assert_called_once_with("\n")
        self.assertEqual(result.confirmed_prompts, ["reload"])
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
