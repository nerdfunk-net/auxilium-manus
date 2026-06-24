"""Tests for run-command executor."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from workflow_steps.run_command.executor import execute


def _device(device_id: str = "device-1") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        status=DeviceStatus.OK,
    )


class RunCommandExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_command_results(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with patch(
            "workflow_steps.run_command.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.run_command.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.run_command.executor.NetmikoService"
        ) as netmiko_cls:
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "Cisco IOS"},
                )
            )

            context = WorkflowContext(
                run_id="run-uuid-1",
                workflow_id="wf-1",
                devices={"device-1": _device()},
            )

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_textfsm": False,
                },
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        self.assertEqual(len(outcomes), 1)
        device = outcomes[0].context.devices["device-1"]
        self.assertIn("node-1", device.command_results)
        self.assertEqual(len(device.command_results["node-1"]), 1)
        self.assertEqual(device.command_results["node-1"][0].command, "show version")
        self.assertIsNotNone(device.command_results["node-1"][0].output_ref)

    async def test_textfsm_summary_uses_row_count(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        parsed = [{"hostname": "r1"}, {"hostname": "r2"}]
        with patch(
            "workflow_steps.run_command.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.run_command.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.run_command.executor.NetmikoService"
        ) as netmiko_cls:
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output=json.dumps(parsed),
                    command_outputs={"show ip route": json.dumps(parsed, indent=2)},
                )
            )

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show ip route"],
                    "use_textfsm": True,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        summary = outcomes[0].context.devices["device-1"].command_results["node-1"][0].summary
        self.assertEqual(summary, "2 row(s) parsed")

    async def test_missing_commands_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={"credential_reference": "lab-ssh", "commands": ["  "]},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

    async def test_defaults_commands_when_missing_from_config(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with patch(
            "workflow_steps.run_command.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.run_command.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.run_command.executor.NetmikoService"
        ) as netmiko_cls:
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "Cisco IOS"},
                )
            )

            outcomes = await execute(
                config={"credential_reference": "lab-ssh"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
            )

        self.assertEqual(
            outcomes[0].context.devices["device-1"].command_results["node-1"][0].command,
            "show version",
        )


if __name__ == "__main__":
    unittest.main()
