"""Tests for the nautobot-defaults merge/normalization helpers."""

from __future__ import annotations

import unittest

from workflow_steps.common.attribute_defaults import (
    merge_nautobot_defaults,
    normalize_defaults_block,
)


class MergeNautobotDefaultsTests(unittest.TestCase):
    def test_fills_missing_scalar_field(self) -> None:
        merged = merge_nautobot_defaults({}, {"role": {"name": "Network"}}, overwrite=False)
        self.assertEqual(merged["role"], {"name": "Network"})

    def test_skip_does_not_overwrite_existing_value(self) -> None:
        existing = {"role": {"name": "Existing"}}
        merged = merge_nautobot_defaults(existing, {"role": {"name": "Network"}}, overwrite=False)
        self.assertEqual(merged["role"], {"name": "Existing"})

    def test_overwrite_replaces_existing_value(self) -> None:
        existing = {"role": {"name": "Existing"}}
        merged = merge_nautobot_defaults(existing, {"role": {"name": "Network"}}, overwrite=True)
        self.assertEqual(merged["role"], {"name": "Network"})

    def test_skip_treats_empty_string_as_missing(self) -> None:
        existing = {"serial": ""}
        merged = merge_nautobot_defaults(existing, {"serial": "ABC123"}, overwrite=False)
        self.assertEqual(merged["serial"], "ABC123")

    def test_nested_partial_device_type_merge(self) -> None:
        existing = {"device_type": {"model": "virtual", "id": "abc"}}
        defaults = {"device_type": {"manufacturer": {"name": "Cisco"}}}
        merged = merge_nautobot_defaults(existing, defaults, overwrite=False)
        self.assertEqual(
            merged["device_type"],
            {"model": "virtual", "id": "abc", "manufacturer": {"name": "Cisco"}},
        )

    def test_custom_fields_merge_per_key_skip(self) -> None:
        existing = {"custom_fields": {"net": "prod", "mounts": None}}
        defaults = {"custom_fields": {"net": "lab", "mounts": "rack1"}}
        merged = merge_nautobot_defaults(existing, defaults, overwrite=False)
        self.assertEqual(merged["custom_fields"], {"net": "prod", "mounts": "rack1"})

    def test_custom_fields_merge_per_key_overwrite(self) -> None:
        existing = {"custom_fields": {"net": "prod"}}
        defaults = {"custom_fields": {"net": "lab"}}
        merged = merge_nautobot_defaults(existing, defaults, overwrite=True)
        self.assertEqual(merged["custom_fields"], {"net": "lab"})

    def test_interfaces_skip_whole_on_name_match(self) -> None:
        existing = {"interfaces": [{"name": "Eth0/0", "type": "REAL"}]}
        defaults = {"interfaces": [{"name": "Eth0/0", "type": "VIRTUAL"}]}
        merged = merge_nautobot_defaults(existing, defaults, overwrite=False)
        self.assertEqual(merged["interfaces"], [{"name": "Eth0/0", "type": "REAL"}])

    def test_interfaces_overwrite_whole_on_name_match(self) -> None:
        existing = {"interfaces": [{"name": "Eth0/0", "type": "REAL"}]}
        defaults = {"interfaces": [{"name": "Eth0/0", "type": "VIRTUAL"}]}
        merged = merge_nautobot_defaults(existing, defaults, overwrite=True)
        self.assertEqual(merged["interfaces"], [{"name": "Eth0/0", "type": "VIRTUAL"}])

    def test_interfaces_append_new_name(self) -> None:
        existing = {"interfaces": [{"name": "Eth0/0"}]}
        defaults = {"interfaces": [{"name": "Eth0/1", "type": "VIRTUAL"}]}
        merged = merge_nautobot_defaults(existing, defaults, overwrite=False)
        names = [item["name"] for item in merged["interfaces"]]
        self.assertEqual(names, ["Eth0/0", "Eth0/1"])

    def test_empty_defaults_is_noop(self) -> None:
        existing = {"role": {"name": "Existing"}}
        merged = merge_nautobot_defaults(existing, {}, overwrite=True)
        self.assertEqual(merged, existing)


class NormalizeDefaultsBlockTests(unittest.TestCase):
    def test_plain_string_named_reference(self) -> None:
        defaults = normalize_defaults_block({"role": "Network"})
        self.assertEqual(defaults["role"], {"name": "Network"})

    def test_tags_single_string_becomes_list(self) -> None:
        defaults = normalize_defaults_block({"tags": "production"})
        self.assertEqual(defaults["tags"], ["production"])

    def test_tags_comma_separated_string(self) -> None:
        defaults = normalize_defaults_block({"tags": "production, lab"})
        self.assertEqual(defaults["tags"], ["production", "lab"])

    def test_device_type_partial_manufacturer_only(self) -> None:
        defaults = normalize_defaults_block(
            {"device_type": {"manufacturer": {"name": "Cisco"}}}
        )
        self.assertEqual(defaults["device_type"], {"manufacturer": {"name": "Cisco"}})

    def test_custom_fields_flat_dict(self) -> None:
        defaults = normalize_defaults_block({"custom_fields": {"net": "lab"}})
        self.assertEqual(defaults["custom_fields"], {"net": "lab"})

    def test_interfaces_normalizes_status_and_ip_addresses(self) -> None:
        defaults = normalize_defaults_block(
            {
                "interfaces": [
                    {
                        "name": "Ethernet0/0",
                        "status": {"name": "Active"},
                        "type": "VIRTUAL",
                        "ip_addresses": ["192.168.178.240/24"],
                    }
                ]
            }
        )
        self.assertEqual(
            defaults["interfaces"],
            [
                {
                    "name": "Ethernet0/0",
                    "type": "VIRTUAL",
                    "status": {"name": "Active"},
                    "ip_addresses": [{"address": "192.168.178.240/24"}],
                }
            ],
        )

    def test_interface_without_name_is_dropped(self) -> None:
        defaults = normalize_defaults_block({"interfaces": [{"status": "Active"}]})
        self.assertNotIn("interfaces", defaults)

    def test_empty_raw_returns_empty_dict(self) -> None:
        self.assertEqual(normalize_defaults_block({}), {})
        self.assertEqual(normalize_defaults_block(None), {})


if __name__ == "__main__":
    unittest.main()
