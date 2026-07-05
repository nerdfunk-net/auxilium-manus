"""Tests for update-nautobot-device field value expressions."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from workflow_steps.common.update_field_expression import (
    build_resolved_update_data,
    config_has_enabled_update_fields,
    normalize_field_spec,
    resolve_update_field_expression,
)


def _device(**kwargs: object) -> DeviceContext:
    defaults = {
        "id": "dev-1",
        "name": "router-1",
        "hostname": "router-1",
        "attribute_bags": {},
        "capabilities": {Capability.IDENTITY},
        "status": DeviceStatus.OK,
    }
    defaults.update(kwargs)
    return DeviceContext(**defaults)  # type: ignore[arg-type]


class UpdateFieldExpressionTests(unittest.TestCase):
    def test_normalize_field_spec_from_new_format(self) -> None:
        enabled, value = normalize_field_spec({"enabled": True, "value": "cityA"})
        self.assertTrue(enabled)
        self.assertEqual(value, "cityA")

    def test_normalize_field_spec_from_legacy_string(self) -> None:
        enabled, value = normalize_field_spec("cityA")
        self.assertTrue(enabled)
        self.assertEqual(value, "cityA")

    def test_fixed_value(self) -> None:
        device = _device()
        self.assertEqual(
            resolve_update_field_expression(
                device=device,
                field_key="location",
                raw_value="cityA",
            ),
            "cityA",
        )

    def test_nautobot_origin_resolves_from_bag(self) -> None:
        device = _device(
            attribute_bags={"nautobot": {"location": {"name": "office-a", "id": "loc-1"}}},
        )
        self.assertEqual(
            resolve_update_field_expression(
                device=device,
                field_key="location",
                raw_value="{nautobot.origin}",
            ),
            "office-a",
        )

    def test_path_expression(self) -> None:
        device = _device(attribute_bags={"custom": {"site": "lab-7"}})
        self.assertEqual(
            resolve_update_field_expression(
                device=device,
                field_key="location",
                raw_value="{custom.site}",
            ),
            "lab-7",
        )

    def test_path_expression_with_default(self) -> None:
        device = _device()
        self.assertEqual(
            resolve_update_field_expression(
                device=device,
                field_key="location",
                raw_value="{custom.site | default('fallback')}",
            ),
            "fallback",
        )

    def test_build_resolved_update_data_only_includes_enabled_fields(self) -> None:
        device = _device(
            attribute_bags={
                "nautobot": {"location": {"name": "office-a"}},
                "custom": {"site": "ignored"},
            },
        )
        payload = build_resolved_update_data(
            device=device,
            raw_fields={
                "location": {"enabled": True, "value": "{nautobot.origin}"},
                "serial": {"enabled": False, "value": "SN123"},
                "status": {"enabled": True, "value": "active"},
            },
        )
        self.assertEqual(payload, {"location": "office-a", "status": "active"})

    def test_config_has_enabled_update_fields(self) -> None:
        self.assertTrue(
            config_has_enabled_update_fields(
                {"location": {"enabled": True, "value": "{nautobot.origin}"}}
            )
        )
        self.assertFalse(
            config_has_enabled_update_fields(
                {"location": {"enabled": False, "value": "cityA"}}
            )
        )


if __name__ == "__main__":
    unittest.main()
