"""Tests for run-command executor."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.pyats.common.exceptions import PyATSAPIError
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
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
        ):
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
                device_sessions=MagicMock(),
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
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
        ):
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
                device_sessions=MagicMock(),
            )

        summary = outcomes[0].context.devices["device-1"].command_results["node-1"][0].summary
        self.assertEqual(summary, "2 row(s) parsed")

    async def test_resolves_credential_scoped_to_triggering_user(self) -> None:
        run = MagicMock()
        run.id = 1
        run.triggered_by_id = 42
        db = MagicMock()
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ) as resolve_mock,
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "Cisco IOS"},
                )
            )

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_textfsm": False,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        resolve_mock.assert_called_once_with(db, "lab-ssh", acting_user_id=42)

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
                device_sessions=MagicMock(),
            )

    async def test_defaults_commands_when_missing_from_config(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
        ):
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
                device_sessions=MagicMock(),
            )

        self.assertEqual(
            outcomes[0].context.devices["device-1"].command_results["node-1"][0].command,
            "show version",
        )


    async def test_use_genie_without_source_id_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_genie": True,
                    "pyats_source_id": "",
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_genie_disabled_leaves_parsed_empty(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "Cisco IOS"},
                )
            )

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_genie": False,
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.parsed, {})
        self.assertNotIn(Capability.PARSED, device.capabilities)

    async def test_genie_parsing_populates_parsed_and_capability(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
            patch(
                "workflow_steps.run_command.executor.PyATSSourceConfigService"
            ) as source_service_cls,
            patch("workflow_steps.run_command.executor.service_factory") as service_factory_mock,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "Cisco IOS raw output"},
                )
            )
            source_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.parse_batch = AsyncMock(
                return_value={
                    "results": {
                        "device-1": {
                            "commands": {
                                "show version": {"parsed": {"version": "16.9"}, "error": None}
                            }
                        }
                    }
                }
            )
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_genie": True,
                    "pyats_source_id": "lab-pyats",
                    "genie_output_key": "genie",
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(
            device.parsed["genie"]["show version"]["parsed"], {"version": "16.9"}
        )
        self.assertIn(Capability.PARSED, device.capabilities)
        shim.parse_batch.assert_awaited_once()

    async def test_genie_per_command_error_does_not_fail_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
            patch(
                "workflow_steps.run_command.executor.PyATSSourceConfigService"
            ) as source_service_cls,
            patch("workflow_steps.run_command.executor.service_factory") as service_factory_mock,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "nonsense"},
                )
            )
            source_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.parse_batch = AsyncMock(
                return_value={
                    "results": {
                        "device-1": {
                            "commands": {
                                "show version": {"parsed": None, "error": "ParserNotFound"}
                            }
                        }
                    }
                }
            )
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_genie": True,
                    "pyats_source_id": "lab-pyats",
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertIsNone(device.parsed["genie"]["show version"]["parsed"])
        self.assertEqual(device.parsed["genie"]["show version"]["error"], "ParserNotFound")

    async def test_genie_infra_failure_does_not_fail_device(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with (
            patch(
                "workflow_steps.run_command.executor.object_session",
                return_value=db,
            ),
            patch(
                "workflow_steps.run_command.executor.resolve_ssh_credential",
                return_value=("admin", "secret"),
            ),
            patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
            patch(
                "workflow_steps.run_command.executor.PyATSSourceConfigService"
            ) as source_service_cls,
            patch("workflow_steps.run_command.executor.service_factory") as service_factory_mock,
        ):
            netmiko = netmiko_cls.return_value
            netmiko.send_commands = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=True,
                    output="Cisco IOS",
                    command_outputs={"show version": "Cisco IOS"},
                )
            )
            source_service_cls.return_value.resolve_credentials.return_value = MagicMock()
            shim = MagicMock()
            shim.parse_batch = AsyncMock(side_effect=PyATSAPIError("shim unreachable"))
            service_factory_mock.get_pyats_app_service.return_value = shim

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "commands": ["show version"],
                    "use_genie": True,
                    "pyats_source_id": "lab-pyats",
                },
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertNotIn("genie", device.parsed)


if __name__ == "__main__":
    unittest.main()
