"""Tests for nautobot attribute bag → update field mapping."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.common.nautobot_update_fields import (
    context_has_nautobot_update_fields,
    extract_update_fields_from_nautobot_bag,
    merge_update_data,
)


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

    def test_merge_prefers_bag_over_config(self) -> None:
        merged = merge_update_data(
            {"location": "static-dc", "serial": "OLD"},
            {"location": "office-a"},
        )
        self.assertEqual(merged, {"location": "office-a", "serial": "OLD"})

    def test_context_has_nautobot_update_fields(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "dev-1": DeviceContext(
                    id="dev-1",
                    name="dev-1",
                    hostname="dev-1",
                    attribute_bags={"nautobot": {"location": {"name": "office-a"}}},
                    status=DeviceStatus.OK,
                )
            },
        )
        self.assertTrue(context_has_nautobot_update_fields(context.devices))


if __name__ == "__main__":
    unittest.main()
