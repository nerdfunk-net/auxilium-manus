"""build_resolved_update_data must not copy a sealed secret into a Nautobot request."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from models.workflow_context import DeviceContext
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.value_expression import build_resolved_update_data


@patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-for-update-fields"})
class BuildResolvedUpdateDataSecretTests(unittest.TestCase):
    def _device(self) -> DeviceContext:
        return DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            attribute_bags={
                "tacacs": {"shared_secret": seal_secret("s3cr3t")},
                "custom": {"serial": "ABC123"},
            },
        )

    def test_plain_attribute_still_resolves(self) -> None:
        data = build_resolved_update_data(
            device=self._device(),
            raw_fields={"serial": {"enabled": True, "value": "{custom.serial}"}},
        )
        self.assertEqual(data, {"serial": "ABC123"})

    def test_sealed_secret_in_a_device_field_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_resolved_update_data(
                device=self._device(),
                raw_fields={"serial": {"enabled": True, "value": "{tacacs.shared_secret}"}},
            )
        self.assertIn("serial", str(ctx.exception))
        self.assertNotIn("s3cr3t", str(ctx.exception))

    def test_sealed_secret_in_a_custom_field_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_resolved_update_data(
                device=self._device(),
                raw_fields={
                    "custom_fields": {
                        "key": {"enabled": True, "value": "{tacacs.shared_secret}"}
                    }
                },
            )
        self.assertIn("key", str(ctx.exception))
        self.assertNotIn("s3cr3t", str(ctx.exception))


class DeviceFieldOrderTests(unittest.TestCase):
    """W2-06: the payload order and the field that fails first do not depend on hash seeds."""

    def test_the_payload_follows_the_declared_field_order(self) -> None:
        from workflow_steps.common.nautobot_update_fields import DEVICE_FIELD_KEYS

        device = DeviceContext(id="d1", name="d1", hostname="d1")
        raw = {
            key: {"enabled": True, "value": f"v-{key}"}
            for key in DEVICE_FIELD_KEYS
            if key != "custom_fields"
        }
        raw["tags"] = {"enabled": True, "value": "a"}
        data = build_resolved_update_data(device=device, raw_fields=raw)
        expected = [k for k in DEVICE_FIELD_KEYS if k != "custom_fields"]
        assert list(data) == expected

    @patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-for-update-fields"})
    def test_the_first_secret_field_in_declared_order_is_the_one_reported(self) -> None:
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            attribute_bags={"tacacs": {"k": seal_secret("s3cr3t")}},
        )
        raw = {
            "serial": {"enabled": True, "value": "{tacacs.k}"},
            "name": {"enabled": True, "value": "{tacacs.k}"},
            "rack": {"enabled": True, "value": "{tacacs.k}"},
        }
        with self.assertRaisesRegex(ValueError, "'name'"):
            build_resolved_update_data(device=device, raw_fields=raw)

    def test_the_field_list_is_declared_once(self) -> None:
        from workflow_steps.common import nautobot_update_fields

        assert len(set(nautobot_update_fields.DEVICE_FIELD_KEYS)) == 16
        assert nautobot_update_fields.DEVICE_FIELD_KEYS[0] == "name"
