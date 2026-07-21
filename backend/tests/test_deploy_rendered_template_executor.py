"""Tests for deploy-rendered-template executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import DeployResult as NetmikoDeployResult
from workflow_steps.deploy_rendered_template.executor import execute

RENDERED_TEXT = "interface Gi0/0\n description test\n"


def _device_with_rendered_template(device_id: str = "device-1") -> DeviceContext:
    artifact_ref = ArtifactRef(
        artifact_id="artifact-rendered",
        kind="rendered_template",
        size_bytes=len(RENDERED_TEXT),
    )
    return DeviceContext(
        id=device_id,
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        parsed={
            "device_config": {
                "artifact_ref": artifact_ref.model_dump(mode="json"),
                "step_node_id": "render-jinja-template-3",
                "output_key": "device_config",
                "size_bytes": len(RENDERED_TEXT),
                "kind": "rendered_template",
            }
        },
        capabilities={Capability.IDENTITY, Capability.PARSED},
        status=DeviceStatus.OK,
    )


def _base_config(**overrides: object) -> dict:
    config = {
        "credential_reference": "lab-ssh",
        "source_step_node_id": "render-jinja-template-3",
        "parsed_output_key": "device_config",
    }
    config.update(overrides)
    return config


class DeployRenderedTemplateExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_deploys_config_mode_by_default(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with patch(
            "workflow_steps.deploy_rendered_template.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.NetmikoService"
        ) as netmiko_cls, patch.object(
            artifact_service, "resolve", new=AsyncMock(return_value=RENDERED_TEXT)
        ):
            netmiko = netmiko_cls.return_value
            netmiko.deploy_config = AsyncMock(
                return_value=NetmikoDeployResult(success=True, config_output="ok")
            )

            outcomes = await execute(
                config=_base_config(),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_rendered_template()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="deploy-1",
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        device = outcomes[0].context.devices["device-1"]
        results = device.command_results["deploy-1"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].command, "deploy-rendered-template")
        self.assertTrue(results[0].success)

        call_kwargs = netmiko.deploy_config.call_args.kwargs
        self.assertEqual(call_kwargs["mode"], "config_mode")
        self.assertEqual(call_kwargs["commands"], ["interface Gi0/0", " description test"])
        self.assertFalse(call_kwargs["write_config"])

    async def test_write_config_after_execution_stores_save_result(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with patch(
            "workflow_steps.deploy_rendered_template.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.NetmikoService"
        ) as netmiko_cls, patch.object(
            artifact_service, "resolve", new=AsyncMock(return_value=RENDERED_TEXT)
        ):
            netmiko = netmiko_cls.return_value
            netmiko.deploy_config = AsyncMock(
                return_value=NetmikoDeployResult(
                    success=True, config_output="ok", save_output="Building configuration...\n"
                )
            )

            outcomes = await execute(
                config=_base_config(write_config_after_execution=True),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_rendered_template()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="deploy-1",
            )

        device = outcomes[0].context.devices["device-1"]
        results = device.command_results["deploy-1"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1].command, "copy running-config startup-config")
        self.assertTrue(results[1].success)
        self.assertTrue(netmiko.deploy_config.call_args.kwargs["write_config"])

    async def test_exec_mode_is_passed_through(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with patch(
            "workflow_steps.deploy_rendered_template.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.NetmikoService"
        ) as netmiko_cls, patch.object(
            artifact_service, "resolve", new=AsyncMock(return_value=RENDERED_TEXT)
        ):
            netmiko = netmiko_cls.return_value
            netmiko.deploy_config = AsyncMock(
                return_value=NetmikoDeployResult(success=True, config_output="ok")
            )

            await execute(
                config=_base_config(execution_mode="exec_mode"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_rendered_template()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="deploy-1",
            )

        self.assertEqual(netmiko.deploy_config.call_args.kwargs["mode"], "exec_mode")

    async def test_missing_source_step_node_id_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={"credential_reference": "lab-ssh"},
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_rendered_template()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="deploy-1",
            )

    async def test_invalid_execution_mode_raises(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config=_base_config(execution_mode="bogus"),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_rendered_template()},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="deploy-1",
            )

    async def test_device_without_rendered_template_fails(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        with patch(
            "workflow_steps.deploy_rendered_template.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ):
            device = DeviceContext(
                id="device-1",
                name="router1",
                hostname="router1",
                network_driver="cisco_ios",
                status=DeviceStatus.OK,
            )
            outcomes = await execute(
                config=_base_config(),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": device},
                ),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="deploy-1",
            )

        names = {outcome.name for outcome in outcomes}
        self.assertIn("failure", names)
        failed_device = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
        self.assertEqual(failed_device.errors[-1].code, "rendered_template_missing")

    async def test_save_failure_marks_device_failed(self) -> None:
        run = MagicMock()
        run.id = 1
        db = MagicMock()
        artifact_service = InMemoryArtifactService()
        with patch(
            "workflow_steps.deploy_rendered_template.executor.object_session",
            return_value=db,
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ), patch(
            "workflow_steps.deploy_rendered_template.executor.NetmikoService"
        ) as netmiko_cls, patch.object(
            artifact_service, "resolve", new=AsyncMock(return_value=RENDERED_TEXT)
        ):
            netmiko = netmiko_cls.return_value
            netmiko.deploy_config = AsyncMock(
                return_value=NetmikoDeployResult(
                    success=False, config_output="", error="save failed"
                )
            )

            outcomes = await execute(
                config=_base_config(write_config_after_execution=True),
                context=WorkflowContext(
                    run_id="run-uuid-1",
                    workflow_id="wf-1",
                    devices={"device-1": _device_with_rendered_template()},
                ),
                run=run,
                artifact_service=artifact_service,
                node_id="deploy-1",
            )

        names = {outcome.name for outcome in outcomes}
        self.assertIn("failure", names)
        failed_device = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
        self.assertEqual(failed_device.errors[-1].code, "deploy_failed")


if __name__ == "__main__":
    unittest.main()
