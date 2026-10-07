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


class DeviceContextFromCatalystCenterTests(unittest.TestCase):
    @staticmethod
    def _device(**overrides):
        from models.catalyst_center import CatalystCenterDevice

        raw = {
            "id": "uuid-1",
            "hostname": "sw1",
            "managementIpAddress": "10.10.20.175",
            "softwareType": "IOS-XE",
            "platformId": "C9KV-UADP-8P",
            "role": "ACCESS",
        }
        raw.update(overrides)
        return CatalystCenterDevice(
            id=raw["id"],
            hostname=raw.get("hostname"),
            management_ip=raw.get("managementIpAddress"),
            software_type=raw.get("softwareType"),
            platform_id=raw.get("platformId"),
            role=raw.get("role"),
            raw=raw,
        )

    def test_maps_identity_fields(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_catalyst_center

        context = device_context_from_catalyst_center(self._device(), source_id="lab-cc")

        self.assertEqual(context.id, "uuid-1")
        self.assertEqual(context.name, "sw1")
        self.assertEqual(context.hostname, "10.10.20.175")  # SSH target prefers the IP
        self.assertEqual(context.primary_ip4, "10.10.20.175")
        self.assertEqual(context.platform, "IOS-XE")
        self.assertEqual(context.network_driver, "cisco_xe")
        self.assertEqual(context.source, "catalyst_center")
        self.assertEqual(context.source_id, "lab-cc")
        self.assertEqual(context.capabilities, {Capability.IDENTITY})

    def test_raw_record_is_kept_in_its_own_bag(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_catalyst_center

        context = device_context_from_catalyst_center(self._device(), source_id="lab-cc")

        self.assertEqual(context.attribute_bags["catalyst_center"]["role"], "ACCESS")
        self.assertEqual(context.attribute_bags["catalyst_center"]["platformId"], "C9KV-UADP-8P")

    def test_bag_is_a_copy_not_the_device_raw_dict(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_catalyst_center

        device = self._device()
        context = device_context_from_catalyst_center(device, source_id="lab-cc")
        context.attribute_bags["catalyst_center"]["role"] = "CORE"
        self.assertEqual(device.raw["role"], "ACCESS")

    def test_network_driver_table(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_catalyst_center

        expected = {
            "IOS-XE": "cisco_xe",
            "IOS-XR": "cisco_xr",
            "NX-OS": "cisco_nxos",
            "IOS": "cisco_ios",
            "ios-xe": "cisco_xe",
            "Unknown-OS": None,
            None: None,
        }
        for software_type, driver in expected.items():
            context = device_context_from_catalyst_center(
                self._device(softwareType=software_type), source_id="s"
            )
            self.assertEqual(context.network_driver, driver, software_type)

    def test_name_falls_back_to_ip_then_id(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_catalyst_center

        no_host = device_context_from_catalyst_center(self._device(hostname=None), source_id="s")
        self.assertEqual(no_host.name, "10.10.20.175")

        bare = device_context_from_catalyst_center(
            self._device(hostname=None, managementIpAddress=None), source_id="s"
        )
        self.assertEqual(bare.name, "uuid-1")
        self.assertEqual(bare.hostname, "uuid-1")
        self.assertIsNone(bare.primary_ip4)

    def test_platform_is_none_when_software_type_missing(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_catalyst_center

        context = device_context_from_catalyst_center(
            self._device(softwareType=None), source_id="s"
        )
        self.assertIsNone(context.platform)


class DeviceContextFromGitDetailTests(unittest.TestCase):
    def test_mapped_detail_sets_core_fields_and_bags(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_git_detail

        detail = {
            "name": "r1",
            "primary_ip4": {"address": "10.0.0.1/24"},
            "platform": {"name": "IOS", "network_driver": "cisco_ios"},
            "location": {"name": "City A"},
        }
        raw = {"device_name": "r1", "site": "City A"}

        context = device_context_from_git_detail(detail, source_id="3", index=0, raw=raw)

        self.assertEqual(context.name, "r1")
        self.assertEqual(context.primary_ip4, "10.0.0.1/24")
        self.assertEqual(context.hostname, "10.0.0.1")
        self.assertEqual(context.platform, "IOS")
        self.assertEqual(context.network_driver, "cisco_ios")
        self.assertEqual(context.attribute_bags["nautobot"], detail)
        self.assertEqual(context.attribute_bags["git"], raw)

    def test_nautobot_bag_is_a_copy(self) -> None:
        from workflow_steps.common.device_builders import device_context_from_git_detail

        detail = {"name": "r1", "location": {"name": "A"}}
        context = device_context_from_git_detail(detail, source_id="3", index=0)
        context.attribute_bags["nautobot"]["location"]["name"] = "B"
        self.assertEqual(detail["location"]["name"], "A")
