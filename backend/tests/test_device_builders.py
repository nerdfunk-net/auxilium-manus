"""Tests for backend/workflow_steps/common/device_builders.py."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability
from workflow_steps.common.device_builders import device_context_from_ise


class DeviceContextFromIseTests(unittest.TestCase):
    def test_tacacs_shared_secret_is_surfaced_as_its_own_bag(self) -> None:
        device = {
            "id": "abc-123",
            "name": "lab",
            "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
            "tacacsSettings": {
                "sharedSecret": "s3cret",
                "connectModeOptions": "OFF",
            },
        }

        context = device_context_from_ise(device, source_id="ise")

        self.assertEqual(context.attribute_bags["tacacs"], {"shared_secret": "s3cret"})
        self.assertEqual(context.attribute_bags["ise"]["name"], "lab")
        self.assertIn(Capability.IDENTITY, context.capabilities)

    def test_no_tacacs_bag_when_tacacs_settings_missing(self) -> None:
        device = {
            "id": "abc-123",
            "name": "radius-only",
            "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
        }

        context = device_context_from_ise(device, source_id="ise")

        self.assertNotIn("tacacs", context.attribute_bags)

    def test_no_tacacs_bag_when_shared_secret_empty(self) -> None:
        device = {
            "id": "abc-123",
            "name": "lab",
            "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
            "tacacsSettings": {"sharedSecret": "", "connectModeOptions": "OFF"},
        }

        context = device_context_from_ise(device, source_id="ise")

        self.assertNotIn("tacacs", context.attribute_bags)


if __name__ == "__main__":
    unittest.main()
