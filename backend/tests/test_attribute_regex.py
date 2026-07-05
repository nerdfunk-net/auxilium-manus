"""Tests for attribute regex helpers."""

from __future__ import annotations

import unittest

from workflow_steps.common.attribute_regex import apply_regex_transform, probe_regex_transform


class AttributeRegexTests(unittest.TestCase):
    def test_probe_returns_groups_and_destination(self) -> None:
        result = probe_regex_transform(
            source_text="l123-router-1.local.zz",
            pattern=r"^([^-]+)-",
            destination_template=r"DC-\1",
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["full_match"], "l123-")
        self.assertEqual(result["groups"], {"1": "l123"})
        self.assertEqual(result["destination_value"], "DC-l123")

    def test_apply_returns_none_when_no_match(self) -> None:
        value = apply_regex_transform(
            source_text="switchonly.local.zz",
            pattern=r"^([^-]+)-",
            destination_template=r"DC-\1",
        )
        self.assertIsNone(value)

    def test_case_insensitive_flag(self) -> None:
        result = probe_regex_transform(
            source_text="L123-router-1.local.zz",
            pattern=r"^([^-]+)-",
            destination_template=r"DC-\1",
            flags={"case_insensitive": True},
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["destination_value"], "DC-L123")

    def test_named_group_template(self) -> None:
        result = probe_regex_transform(
            source_text="l123-router-1.local.zz",
            pattern=r"^(?P<site>[^-]+)-router",
            destination_template=r"DC-\g<site>",
        )
        self.assertEqual(result["named_groups"], {"site": "l123"})
        self.assertEqual(result["destination_value"], "DC-l123")


if __name__ == "__main__":
    unittest.main()
