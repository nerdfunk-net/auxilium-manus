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

        args, kwargs = connection.send_config_set.call_args
        self.assertEqual(args, (["no username bob"],))
        self.assertEqual(kwargs["read_timeout"], 120)
        self.assertFalse(kwargs["exit_config_mode"])
        connection.exit_config_mode.assert_called_once()
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

    def test_auto_confirm_prompts_exec_mode_answers_destination_filename(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as connect_handler_cls:
            connection = connect_handler_cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.send_command.return_value = "Destination filename [startup-config]? "
            connection.read_until_prompt.return_value = "\n[OK]\nLAB#"

            result = session.deploy_config(
                ["copy running-config startup-config"],
                mode="exec_mode",
                auto_confirm_prompts=True,
            )

        connection.write_channel.assert_called_once_with("\n")
        self.assertEqual(result.confirmed_prompts, ["copy running-config startup-config"])
        self.assertTrue(result.success)


def _session_of(device_type: str) -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1", device_type=device_type, username="admin", password="secret"
    )


class NetmikoDeployRejectionTests(unittest.TestCase):
    """CF-04: a refused configuration line is a failed device (C2-01)."""

    def test_netmiko_exception_fails_deploy_without_leaking_command(self) -> None:
        from netmiko.exceptions import ConfigInvalidException

        session = _session()
        commands = ["interface Gi0/1", "tacacs-server key hunter2", "end"]
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.side_effect = ConfigInvalidException(
                "Invalid input detected at command: tacacs-server key hunter2, "
                "matched error: % Invalid input detected"
            )
            result = session.deploy_config(commands, mode="config_mode")

        self.assertFalse(result.success)
        assert result.failure is not None
        self.assertEqual(result.failure.kind, "config_rejected")
        self.assertIn("command 2 of 3", result.error or "")
        self.assertNotIn("hunter2", result.error or "")
        self.assertNotIn("hunter2", repr(result.failure))
        # never hand a pooled session back in config mode (C2-05)
        connection.exit_config_mode.assert_called_once()

    def test_deploy_leaves_config_mode_on_timeout(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.side_effect = RuntimeError("Pattern not detected")
            result = session.deploy_config(["interface Gi0/0"], mode="config_mode")
        self.assertFalse(result.success)
        connection.exit_config_mode.assert_called_once()

    def test_clean_deploy_is_success(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.return_value = "interface Gi0/1\nLAB(config-if)#"
            connection.exit_config_mode.return_value = "LAB#"
            result = session.deploy_config(["interface Gi0/1"], mode="config_mode")
        self.assertTrue(result.success)
        connection.commit.assert_not_called()

    def test_auto_confirm_path_stops_at_first_refusal(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "LAB"
            connection.RETURN = "\n"
            connection.config_mode.return_value = "LAB(config)#"
            connection.exit_config_mode.return_value = "LAB#"
            connection.send_command.side_effect = [
                "one\nLAB(config)#",
                "two\n% Invalid input detected at '^' marker.\nLAB(config)#",
                "three\nLAB(config)#",
            ]
            result = session.deploy_config(
                ["one", "two", "three"], mode="config_mode", auto_confirm_prompts=True
            )
        self.assertFalse(result.success)
        self.assertEqual(connection.send_command.call_count, 2)
        self.assertIn("command 2 of 3", result.error or "")
        self.assertIn("% Invalid input detected", result.config_output)
        connection.exit_config_mode.assert_called_once()

    def test_exec_mode_stops_at_first_refusal(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_command.side_effect = ["ok", "% Incomplete command.", "never"]
            result = session.deploy_config(["a", "b", "c"], mode="exec_mode")
        self.assertFalse(result.success)
        self.assertEqual(connection.send_command.call_count, 2)

    def test_fail_on_cli_error_false_keeps_old_behaviour(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.return_value = "% Invalid input detected"
            connection.exit_config_mode.return_value = "LAB#"
            result = session.deploy_config(["x"], mode="config_mode", fail_on_cli_error=False)
        self.assertTrue(result.success)
        self.assertEqual(connection.send_config_set.call_args.kwargs["error_pattern"], "")

    def test_service_skips_save_when_deploy_rejected(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from services.network.netmiko.service import NetmikoService

        session = MagicMock()
        session.deploy_config.return_value = _session()._config_rejected(
            ["x"], 0, "invalid_input", "out", []
        )
        pool = MagicMock()

        async def run_on_device(**kwargs):
            return kwargs["op"](session)

        pool.run_on_device = run_on_device
        result = asyncio.run(
            NetmikoService(pool=pool).deploy_config(
                host="h",
                network_driver=None,
                platform="ios",
                username="u",
                password="p",
                commands=["x"],
                mode="config_mode",
                write_config=True,
                credential_reference="",
            )
        )
        self.assertFalse(result.success)
        session.save_running_config.assert_not_called()


class NetmikoCommitModelTests(unittest.TestCase):
    """CF-04 step 5: IOS-XR and Junos need an explicit commit."""

    def test_xr_deploy_commits_before_leaving_config_mode(self) -> None:
        session = _session_of("cisco_xr")
        calls: list[str] = []
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.return_value = "ok"
            connection.commit.side_effect = lambda **kw: calls.append("commit") or "Commit complete"
            connection.exit_config_mode.side_effect = lambda: calls.append("exit") or ""
            result = session.deploy_config(["hostname x"], mode="config_mode")
        self.assertTrue(result.success)
        self.assertEqual(calls, ["commit", "exit"])

    def test_ios_deploy_does_not_call_commit(self) -> None:
        session = _session_of("cisco_ios")
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.return_value = "ok"
            session.deploy_config(["hostname x"], mode="config_mode")
        connection.commit.assert_not_called()

    def test_failed_commit_fails_device(self) -> None:
        session = _session_of("juniper_junos")
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.return_value = "ok"
            connection.commit.return_value = (
                "error: commit failed: (statements constraint check failed)"
            )
            result = session.deploy_config(["set system host-name x"], mode="config_mode")
        self.assertFalse(result.success)
        connection.send_command_timing.assert_called_with("rollback 0")
        connection.exit_config_mode.assert_called()

    def test_raised_commit_failure_drops_transcript_and_discards_candidate(self) -> None:
        # Netmiko 4.x raises ValueError with the whole CLI transcript on a refused commit.
        session = _session_of("juniper_junos")
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.return_value = "ok"
            connection.commit.side_effect = ValueError(
                "Commit failed with the following errors:\n\nset tacacs key TOPSECRET\nerror"
            )
            result = session.deploy_config(["set tacacs key TOPSECRET"], mode="config_mode")
        self.assertFalse(result.success)
        self.assertNotIn("TOPSECRET", result.error or "")
        self.assertNotIn("TOPSECRET", result.config_output or "")
        self.assertEqual(result.failure.kind, "config_rejected")
        connection.send_command_timing.assert_called_with("rollback 0")
        connection.exit_config_mode.assert_called()

    def test_unexpected_error_in_config_mode_discards_candidate(self) -> None:
        session = _session_of("juniper_junos")
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.send_config_set.side_effect = OSError("socket closed")
            result = session.deploy_config(["set a b"], mode="config_mode")
        self.assertFalse(result.success)
        connection.send_command_timing.assert_called_with("rollback 0")

    def test_rejected_line_is_not_committed(self) -> None:
        session = _session_of("cisco_xr")
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "XR"
            connection.RETURN = "\n"
            connection.config_mode.return_value = "XR(config)#"
            connection.exit_config_mode.return_value = ""
            connection.send_command.return_value = "% Invalid input detected\nXR(config)#"
            result = session.deploy_config(["bad"], mode="config_mode", auto_confirm_prompts=True)
        self.assertFalse(result.success)
        connection.commit.assert_not_called()


class NetmikoGetConfigsTests(unittest.TestCase):
    def _configs(self, running: str, startup: str):
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            cls.return_value.send_command.side_effect = [running, startup]
            return session.get_configs()

    def test_refused_startup_config_fails_and_is_not_stored(self) -> None:
        result = self._configs("hostname r1\nend", "Command authorization failed.")
        self.assertFalse(result.success)
        self.assertIsNone(result.startup_config)
        self.assertIn("startup-config", result.error or "")
        self.assertIn("authorization_failed", result.error or "")

    def test_empty_running_config_fails(self) -> None:
        result = self._configs("   ", "hostname r1")
        self.assertFalse(result.success)
        self.assertIn("empty", result.error or "")

    def test_short_config_is_not_empty(self) -> None:
        result = self._configs("end", "end")
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
