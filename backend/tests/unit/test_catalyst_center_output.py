"""clean_command_output strips the echoed command and trailing prompt."""

from __future__ import annotations

import unittest

from services.catalyst_center.common.output import clean_command_output


class CleanCommandOutputTests(unittest.TestCase):
    def test_strips_echo_and_prompt(self) -> None:
        raw = "show clock\n*15:22:13.553 UTC Fri Oct 3 2026\nsw1#"
        self.assertEqual(
            clean_command_output("show clock", raw), "*15:22:13.553 UTC Fri Oct 3 2026"
        )

    def test_strips_echo_with_prompt_prefix(self) -> None:
        raw = "sw1#show clock\n15:22:13\nsw1#\n"
        self.assertEqual(clean_command_output("show clock", raw), "15:22:13")

    def test_keeps_multiline_body_and_inner_blank_lines(self) -> None:
        raw = "show version\nline1\n\nline2\nsw1#"
        self.assertEqual(clean_command_output("show version", raw), "line1\n\nline2")

    def test_normalizes_crlf(self) -> None:
        raw = "show clock\r\n15:22:13\r\nsw1#"
        self.assertEqual(clean_command_output("show clock", raw), "15:22:13")

    def test_output_without_echo_or_prompt_is_unchanged(self) -> None:
        self.assertEqual(clean_command_output("show x", "plain output"), "plain output")

    def test_does_not_strip_a_first_line_that_only_ends_with_the_command(self) -> None:
        raw = "this is not show clock\nbody"
        self.assertEqual(clean_command_output("show clock", raw), raw)

    def test_config_mode_prompt_is_stripped(self) -> None:
        self.assertEqual(clean_command_output("x", "x\nbody\nsw1(config-if)#"), "body")

    def test_empty_output(self) -> None:
        self.assertEqual(clean_command_output("show x", "show x\nsw1#"), "")
