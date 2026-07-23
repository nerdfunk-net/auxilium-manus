"""Tests for workflow-log executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.crypto import EncryptionService
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret
from workflow_steps.common.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.workflow_log.executor import execute

_ENC = EncryptionService("test-secret-key-for-workflow-log")


class WorkflowLogExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_interpolates_placeholders_per_device(self) -> None:
        run = MagicMock()
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            network_driver="cisco_ios",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        message = "{device.name} is {device.network_driver} ({nautobot.role.name})"
        outcomes = await execute(
            config={"message": message},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-1",
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, context.devices)

        debug_logs = outcomes[0].context.metadata[f"workflow-log-1{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["message"], message)
        self.assertEqual(debug_logs["device_count"], 1)
        self.assertEqual(
            debug_logs["devices"]["device-1"]["message"],
            "lab is cisco_ios (access-switch)",
        )

    async def test_unresolved_placeholder_renders_empty(self) -> None:
        run = MagicMock()
        device = DeviceContext(id="device-1", name="lab", hostname="lab")
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={"message": "key={tacacs.shared_secret}"},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-1",
        )

        debug_logs = outcomes[0].context.metadata[f"workflow-log-1{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["devices"]["device-1"]["message"], "key=")

    async def test_sealed_secret_placeholder_is_redacted_not_cleartext(self) -> None:
        """workflow-log writes into INFO logs and persisted step metadata, so a
        sealed secret must never be rehydrated here — it should render as the
        redacted placeholder, not the cleartext value."""
        run = MagicMock()
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": sealed}},
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        # reveal_secrets=False short-circuits before any decrypt attempt, so
        # this assertion holds even without a usable encryption key configured.
        outcomes = await execute(
            config={"message": "key={tacacs.shared_secret}"},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-1",
        )

        debug_logs = outcomes[0].context.metadata[f"workflow-log-1{DEBUG_LOGS_METADATA_SUFFIX}"]
        message = debug_logs["devices"]["device-1"]["message"]
        self.assertEqual(message, f"key={REDACTED_PLACEHOLDER}")
        self.assertNotIn("s3cr3t", message)

    async def test_passes_through_when_no_devices(self) -> None:
        run = MagicMock()
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={})

        outcomes = await execute(
            config={"message": "{device.name}"},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-2",
        )

        self.assertEqual(outcomes[0].context.devices, {})
        debug_logs = outcomes[0].context.metadata[f"workflow-log-2{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["device_count"], 0)
        self.assertEqual(debug_logs["devices"], {})

    async def test_falls_back_to_default_message_when_omitted(self) -> None:
        run = MagicMock()
        device = DeviceContext(
            id="device-1", name="lab", hostname="lab", network_driver="cisco_ios"
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="workflow-log-3",
        )

        debug_logs = outcomes[0].context.metadata[f"workflow-log-3{DEBUG_LOGS_METADATA_SUFFIX}"]
        self.assertEqual(debug_logs["devices"]["device-1"]["message"], "Device lab: cisco_ios")


if __name__ == "__main__":
    unittest.main()
