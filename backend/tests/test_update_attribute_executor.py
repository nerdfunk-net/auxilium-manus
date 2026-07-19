"""Tests for update-attribute executor."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from core.crypto import EncryptionService
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import is_sealed_secret, seal_secret, unwrap_secret
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.update_attribute.executor import execute

_ENC = EncryptionService("test-secret-key-for-update-attribute")


def _device(
    device_id: str,
    *,
    name: str | None = None,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


@patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-for-update-attribute"})
class UpdateAttributeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_mode_writes_literal_value(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1")},
        )

        outcomes = await execute(
            config={
                "mode": "fixed",
                "destination_path": "custom.location",
                "fixed_value": "office-a",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        self.assertEqual(len(outcomes), 1)
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "custom.location"), "office-a")
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)

    async def test_regex_mode_skips_when_pattern_does_not_match(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1", name="switchonly.local.zz")},
        )

        outcomes = await execute(
            config={
                "mode": "regex",
                "source_path": "device.name",
                "destination_path": "custom.location",
                "pattern": r"^([^-]+)-",
                "destination_template": r"DC-\1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertIsNone(resolve_device_attribute(updated, "custom.location"))
        self.assertEqual(outcomes[0].context.metadata["node-1.skipped_count"], 1)

    async def test_regex_mode_writes_expanded_value(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1", name="l123-router-1.local.zz")},
        )

        outcomes = await execute(
            config={
                "mode": "regex",
                "source_path": "device.name",
                "destination_path": "custom.location",
                "pattern": r"^([^-]+)-",
                "destination_template": r"DC-\1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "custom.location"), "DC-l123")
        self.assertEqual(outcomes[0].context.metadata["node-1.updated_count"], 1)


    async def test_fixed_mode_writing_known_secret_path_is_sealed(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": _device("dev-1")},
        )

        outcomes = await execute(
            config={
                "mode": "fixed",
                "destination_path": "tacacs.shared_secret",
                "fixed_value": "mykey",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
        )

        updated = outcomes[0].context.devices["dev-1"]
        stored = updated.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(stored))
        self.assertEqual(unwrap_secret(stored), "mykey")

    async def test_regex_mode_cannot_read_a_sealed_secret_source(self) -> None:
        """Regression for the confirmed sealing bypass: update-attribute must
        not rehydrate a sealed secret and copy it into an arbitrary plaintext
        destination — it should fail closed instead."""
        run = MagicMock()
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        device = _device("dev-1", attribute_bags={"tacacs": {"shared_secret": sealed}})
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"dev-1": device},
        )

        with self.assertRaises(ValueError) as ctx:
            await execute(
                config={
                    "mode": "regex",
                    "source_path": "tacacs.shared_secret",
                    "destination_path": "backup.token",
                    "pattern": r"(.*)",
                    "destination_template": r"\1",
                },
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="node-1",
            )

        self.assertIn("sealed secret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
