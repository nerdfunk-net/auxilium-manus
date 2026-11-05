"""build_resolved_update_data must not copy a sealed secret into a Nautobot request."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from models.workflow_context import DeviceContext
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.update_field_expression import build_resolved_update_data


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
