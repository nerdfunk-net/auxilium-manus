"""Tests for backend/workflow_steps/common/device_builders.py."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from models.workflow_context import Capability
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.common.device_builders import device_context_from_ise


@patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-for-device-builders"})
class DeviceContextFromIseTests(unittest.TestCase):
    def test_tacacs_shared_secret_is_surfaced_as_its_own_bag_sealed(self) -> None:
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

        sealed = context.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed), "s3cret")
        self.assertEqual(context.attribute_bags["ise"]["name"], "lab")
        self.assertIn(Capability.IDENTITY, context.capabilities)

    def test_nested_ise_tacacs_settings_shared_secret_is_sealed_too(self) -> None:
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

        nested = context.attribute_bags["ise"]["tacacsSettings"]["sharedSecret"]
        self.assertTrue(is_sealed_secret(nested))
        self.assertEqual(unwrap_secret(nested), "s3cret")
        # Sibling settings must survive untouched.
        self.assertEqual(
            context.attribute_bags["ise"]["tacacsSettings"]["connectModeOptions"], "OFF"
        )

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
