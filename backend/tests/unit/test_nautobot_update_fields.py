"""Tests for nautobot attribute bag → update field mapping."""

from __future__ import annotations

import importlib.util
import unittest

from workflow_steps.common.value_expression import extract_update_fields_from_nautobot_bag


def test_the_bag_mapping_lives_in_value_expression() -> None:
    """W2-10: the mapping has one module, next to the value expressions of the same fields."""
    assert importlib.util.find_spec("workflow_steps.common.nautobot_update_fields") is None


class NautobotUpdateFieldsTests(unittest.TestCase):
    def test_extracts_location_name_from_nested_bag(self) -> None:
        fields = extract_update_fields_from_nautobot_bag(
            {"location": {"name": "office-a", "id": "abc-123"}}
        )
        self.assertEqual(fields, {"location": "office-a"})

    def test_extracts_scalar_and_reference_fields(self) -> None:
        fields = extract_update_fields_from_nautobot_bag(
            {
                "serial": "SN123",
                "role": {"name": "access-switch"},
                "device_type": {"model": "C9300-24T"},
                "primary_ip4": {"address": "10.0.0.1/24"},
                "tags": [{"name": "lab"}, "prod"],
                "custom_fields": {"site_code": "NYC1"},
            }
        )
        self.assertEqual(
            fields,
            {
                "serial": "SN123",
                "role": "access-switch",
                "device_type": "C9300-24T",
                "primary_ip4": "10.0.0.1/24",
                "tags": ["lab", "prod"],
                "custom_fields": {"site_code": "NYC1"},
            },
        )

    def test_extracts_secrets_group_name_from_bag(self) -> None:
        fields = extract_update_fields_from_nautobot_bag(
            {"secrets_group": {"id": "sg-1", "name": "ssh-creds"}}
        )
        self.assertEqual(fields, {"secrets_group": "ssh-creds"})

    def test_extracts_secrets_group_plain_string(self) -> None:
        fields = extract_update_fields_from_nautobot_bag({"secrets_group": "ssh-creds"})
        self.assertEqual(fields, {"secrets_group": "ssh-creds"})

    def test_blank_text_is_left_out_and_text_is_stripped(self) -> None:
        """Characterization of the empty handling the merge kept (``strip_empty``)."""
        fields = extract_update_fields_from_nautobot_bag(
            {
                "serial": "  SN9 ",
                "asset_tag": "   ",
                "role": {"name": " ", "id": " role-id "},
                "status": "  ",
                "location": " Lab ",
                "device_type": {"model": "", "name": " C9300 "},
                "primary_ip4": {"address": " ", "host": " 10.0.0.9 "},
                "tags": ["  ", " a ", {"name": " b "}],
                "position": 0,
            }
        )
        self.assertEqual(
            fields,
            {
                "serial": "SN9",
                "role": "role-id",
                "location": "Lab",
                "device_type": "C9300",
                "primary_ip4": "10.0.0.9",
                "tags": ["a", "b"],
                "position": "0",
            },
        )


if __name__ == "__main__":
    unittest.main()
