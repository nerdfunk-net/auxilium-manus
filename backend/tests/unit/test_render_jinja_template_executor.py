"""Tests for render-jinja-template executor."""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.render_jinja_template.executor import execute


class RenderJinjaTemplateExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_renders_per_device_and_stores_parsed_output(self) -> None:
        run = MagicMock()
        run.id = 7
        artifact_service = InMemoryArtifactService()
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "output_key": "device_config",
                "template": "hostname {{ device.hostname }}\nrole {{ nautobot.role.name }}",
            },
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="render-jinja-template-1",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        self.assertIn(Capability.PARSED, success.capabilities)
        entry = success.parsed["device_config"]
        self.assertEqual(entry["output_key"], "device_config")
        self.assertEqual(entry["kind"], "rendered_template")
        content = await artifact_service.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertIn("hostname lab", content)
        self.assertIn("role access-switch", content)

    async def test_render_runs_off_the_event_loop(self) -> None:
        from workflow_steps.render_jinja_template import executor as mod

        real_render = mod.render_jinja_template

        def slow_render(*args, **kwargs):  # noqa: ANN002, ANN003
            time.sleep(0.3)  # blocks its thread, not the event loop
            return real_render(*args, **kwargs)

        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"device-1": device})
        ticks = 0

        async def heartbeat() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(heartbeat())
        try:
            with patch.object(mod, "render_jinja_template", slow_render):
                await execute(
                    config={"output_key": "cfg", "template": "hostname {{ device.hostname }}"},
                    context=context,
                    run=MagicMock(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="render-jinja-template-1",
                    device_sessions=MagicMock(),
                )
        finally:
            task.cancel()
        self.assertGreater(ticks, 3)

    async def test_marks_device_failed_on_template_error(self) -> None:
        run = MagicMock()
        run.id = 7
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "output_key": "device_config",
                "template": "{{ missing.value }}",
            },
            context=context,
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="render-jinja-template-2",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 2)
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "template_error")

    async def test_exposes_upstream_command_output_to_template(self) -> None:
        run = MagicMock()
        run.id = 7
        artifact_service = InMemoryArtifactService()
        textfsm_rows = '[{"interface": "Ethernet0/0", "status": "up"}]'
        output_ref = await artifact_service.store(
            content=textfsm_rows,
            kind="command_output",
            device_id="device-1",
            run_id="run-1",
            media_type="application/json",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            command_results={
                "run-command-2": [
                    CommandResult(
                        node_id="run-command-2",
                        command="show ip int brief",
                        success=True,
                        output_ref=output_ref,
                        summary="1 row(s) parsed",
                    )
                ]
            },
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "output_key": "device_config",
                "template": ("{{ command.parsed[0].interface }} is {{ command.parsed[0].status }}"),
            },
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="render-jinja-template-3",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        entry = success.parsed["device_config"]
        content = await artifact_service.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertEqual(content, "Ethernet0/0 is up")

    async def test_differentiates_multiple_commands_by_name(self) -> None:
        run = MagicMock()
        run.id = 7
        artifact_service = InMemoryArtifactService()
        interfaces_ref = await artifact_service.store(
            content='[{"interface": "Ethernet0/0", "status": "up"}]',
            kind="command_output",
            device_id="device-1",
            run_id="run-1",
            media_type="application/json",
        )
        version_ref = await artifact_service.store(
            content='[{"version": "15.2"}]',
            kind="command_output",
            device_id="device-1",
            run_id="run-1",
            media_type="application/json",
        )
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            command_results={
                "run-command-2": [
                    CommandResult(
                        node_id="run-command-2",
                        command="show ip int brief",
                        success=True,
                        output_ref=interfaces_ref,
                        summary="1 row(s) parsed",
                    ),
                    CommandResult(
                        node_id="run-command-2",
                        command="show version",
                        success=True,
                        output_ref=version_ref,
                        summary="1 row(s) parsed",
                    ),
                ]
            },
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"device-1": device},
        )

        outcomes = await execute(
            config={
                "output_key": "device_config",
                "template": (
                    "{{ commands_by_name['show ip int brief'].parsed[0].interface }}"
                    " / {{ commands_by_name['show version'].parsed[0].version }}"
                    " / count={{ commands | length }}"
                ),
            },
            context=context,
            run=run,
            artifact_service=artifact_service,
            node_id="render-jinja-template-3",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        success = outcomes[0].context.devices["device-1"]
        entry = success.parsed["device_config"]
        content = await artifact_service.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertEqual(content, "Ethernet0/0 / 15.2 / count=2")


if __name__ == "__main__":
    unittest.main()


class UnsafeValueTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, config_extra: dict) -> list:
        run = MagicMock()
        run.id = 7
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"nautobot": {"desc": "uplink\nusername backdoor secret 0 Pwned!"}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1", workflow_id="wf-1", devices={"device-1": device}
        )
        return await execute(
            config={
                "output_key": "device_config",
                "template": "description {{ nautobot.desc }}",
                **config_extra,
            },
            context=context,
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
            device_sessions=MagicMock(),
        )

    async def test_unsafe_value_fails_the_device_with_failure_record(self) -> None:
        outcomes = await self._run({})
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.errors[-1].failure.kind, "unsafe_template_value")

    async def test_opt_out_renders_the_value(self) -> None:
        outcomes = await self._run({"allow_multiline_values": True})
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertIn("device-1", outcomes[0].context.devices)
