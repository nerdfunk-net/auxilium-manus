"""Tests for attribute regex helpers."""

from __future__ import annotations

import unittest

from services.workflow_context.attribute_regex import apply_regex_transform, probe_regex_transform


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

    def test_modifier_upper_and_lower(self) -> None:
        kwargs = {"source_text": "l123-Router-1", "pattern": r"^([^-]+)-([^-]+)-"}
        upper = probe_regex_transform(destination_template=r"DC-{{ \1 | upper }}", **kwargs)
        self.assertEqual(upper["destination_value"], "DC-L123")
        lower = probe_regex_transform(destination_template=r"{{ \g<2> | lower }}", **kwargs)
        self.assertEqual(lower["destination_value"], "router")

    def test_modifier_chain_and_mixed_text_inside_braces(self) -> None:
        result = probe_regex_transform(
            source_text="  ab-cd ",
            pattern=r"^(\s*ab)-(cd\s*)$",
            destination_template=r"x-{{ \1-\2 | strip | upper }}-y",
        )
        self.assertEqual(result["destination_value"], "x-AB-CD-y")

    def test_braces_without_modifier_expand_backrefs(self) -> None:
        result = probe_regex_transform(
            source_text="l1-r", pattern=r"^([^-]+)-", destination_template=r"{{ \1 }}!"
        )
        self.assertEqual(result["destination_value"], "l1!")

    def test_unknown_modifier_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown modifier 'reverse'"):
            probe_regex_transform(
                source_text="l1-r",
                pattern=r"^([^-]+)-",
                destination_template=r"{{ \1 | reverse }}",
            )

    def test_invalid_group_reference_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid destination_template"):
            probe_regex_transform(
                source_text="l1-r", pattern=r"^([^-]+)-", destination_template=r"\5"
            )


if __name__ == "__main__":
    unittest.main()
