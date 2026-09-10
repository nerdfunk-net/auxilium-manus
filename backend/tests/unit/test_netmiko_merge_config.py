"""Tests for NetmikoDeviceSession.merge_running_config (the merge-config step)."""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.network.netmiko.connection import (
    _MERGE_MAX_PROMPT_ANSWERS,
    NetmikoDeviceSession,
)

_DEST_PROMPT = "Building configuration...\nDestination filename [running-config]? "
_BASE = "\n[OK - 1024 bytes]\n\n1024 bytes copied in 0.4 secs (2560 bytes/sec)\nR1#"


def _session() -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1",
        device_type="cisco_ios",
        username="admin",
        password="secret",
    )


class MergeRunningConfigTests(unittest.TestCase):
    def test_answers_destination_filename_prompt(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = _DEST_PROMPT
            connection.read_until_pattern.return_value = _BASE

            result = session.merge_running_config("flash:partial.cfg")

        connection.write_channel.assert_called_once_with("\n")
        self.assertTrue(result.success)
        self.assertEqual(result.confirmed_prompts, ["destination filename"])
        self.assertIn("1024 bytes copied", result.output)
        self.assertIn(
            "copy flash:partial.cfg running-config", result.command_outputs
        )

    def test_no_prompt_when_file_prompt_quiet(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = (
                "Building configuration...\n[OK]\n1024 bytes copied in 0.4 secs\nR1#"
            )

            result = session.merge_running_config("flash:partial.cfg")

        connection.write_channel.assert_not_called()
        connection.read_until_pattern.assert_not_called()
        self.assertTrue(result.success)
        self.assertEqual(result.confirmed_prompts, [])

    def test_answers_unexpected_extra_confirm_prompt(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = _DEST_PROMPT
            connection.read_until_pattern.side_effect = [
                "This operation will remove all username related configurations "
                "with same name.Do you want to continue? [confirm]",
                _BASE,
            ]

            result = session.merge_running_config("flash:partial.cfg")

        self.assertEqual(connection.write_channel.call_count, 2)
        self.assertEqual(
            result.confirmed_prompts, ["destination filename", "confirm"]
        )
        self.assertTrue(result.success)

    def test_copy_error_line_fails_device(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = (
                "copy flash:missing.cfg running-config\n"
                "%Error opening flash:missing.cfg (No such file or directory)\nR1#"
            )

            result = session.merge_running_config("flash:missing.cfg")

        connection.write_channel.assert_not_called()
        self.assertFalse(result.success)
        self.assertEqual(
            result.error,
            "%Error opening flash:missing.cfg (No such file or directory)",
        )

    def test_invalid_input_line_fails_device(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = (
                _DEST_PROMPT
            )
            connection.read_until_pattern.return_value = (
                "\n% Invalid input detected at '^' marker.\nR1#"
            )

            result = session.merge_running_config("flash:partial.cfg")

        self.assertFalse(result.success)
        self.assertIn("Invalid input detected", result.error or "")

    def test_warning_line_fails_device(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = _DEST_PROMPT
            connection.read_until_pattern.return_value = (
                "\n%Warning: could not apply line 12\nR1#"
            )

            result = session.merge_running_config("flash:partial.cfg")

        self.assertFalse(result.success)
        self.assertIn("%Warning", result.error or "")

    def test_bounded_loop_aborts_when_prompt_never_clears(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = _DEST_PROMPT
            connection.read_until_pattern.return_value = "still asking [confirm]"
            connection.read_until_prompt.return_value = "\nR1#"

            result = session.merge_running_config("flash:partial.cfg")

        self.assertFalse(result.success)
        self.assertIn("still prompting", result.error or "")
        connection.read_until_prompt.assert_called_once()
        # one RETURN per answered prompt plus the final drain nudge
        self.assertEqual(
            connection.write_channel.call_count, _MERGE_MAX_PROMPT_ANSWERS + 1
        )

    def test_exception_mid_load_is_normalised(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = _DEST_PROMPT
            connection.read_until_pattern.side_effect = RuntimeError("boom")

            result = session.merge_running_config("flash:partial.cfg")

        self.assertFalse(result.success)
        self.assertIn("boom", result.error or "")
        self.assertEqual(result.output, "")

    def test_read_timeout_passed_through(self) -> None:
        session = _session()
        with patch("services.network.netmiko.connection.ConnectHandler") as cls:
            connection = cls.return_value
            connection.base_prompt = "R1"
            connection.RETURN = "\n"
            connection.send_command.return_value = _DEST_PROMPT
            connection.read_until_pattern.return_value = _BASE

            session.merge_running_config("flash:partial.cfg", read_timeout=120)

        self.assertEqual(connection.send_command.call_args.kwargs["read_timeout"], 120)
        self.assertEqual(
            connection.read_until_pattern.call_args.kwargs["read_timeout"], 120
        )

    def test_confirm_prompt_pattern_no_args_is_byte_identical(self) -> None:
        session = _session()
        session._connection = SimpleNamespace(base_prompt="R1")
        self.assertEqual(
            session._confirm_prompt_pattern(), r"(?:R1.*$|#\s*$|confirm)"
        )

    def test_merge_pattern_matches_real_prompt_casing(self) -> None:
        # Netmiko compiles expect_string case-sensitively (with re.M); IOS prints
        # "Destination filename ...", so the cue must match despite the capital D.
        session = _session()
        session._connection = SimpleNamespace(base_prompt="LAB")
        pattern = session._confirm_prompt_pattern(extra_cues=("destination filename",))
        self.assertIsNotNone(
            re.search(pattern, "Destination filename [running-config]? ", flags=re.M)
        )
        self.assertIsNotNone(re.search(pattern, "LAB#", flags=re.M))
        self.assertIsNone(re.search(pattern, "show version", flags=re.M))


if __name__ == "__main__":
    unittest.main()
