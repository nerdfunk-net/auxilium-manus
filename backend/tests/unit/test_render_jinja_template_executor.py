"""Tests for render-jinja-template executor."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.render_jinja_template.executor import execute as _execute

_LOAD_STORED = "workflow_steps.render_jinja_template.executor.load_stored_template"


async def execute(*, config: dict, **kwargs):  # noqa: ANN003, ANN201
    """Run the step with ``config["template"]`` as the body of stored template 1.

    The step only reads stored templates (``template_id``); the tests that need a body write it
    inline here and this wrapper stores it.
    """
    if "template" not in config:
        return await _execute(config=config, **kwargs)
    stored = {k: v for k, v in config.items() if k != "template"} | {"template_id": 1}
    with patch(_LOAD_STORED, return_value=config["template"]):
        return await _execute(config=stored, **kwargs)


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
        # S4-07: a template that never ends runs in the killable child; the loop keeps ticking
        # until the child is stopped (one second here instead of ten).
        from core import isolated_process

        runaway = (
            "{% for a in range(100000) %}{% for b in range(100000) %}{{ a }}"
            "{% endfor %}{% endfor %}"
        )

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
            with patch.object(isolated_process, "STEP_CHILD_SECONDS", 1.0):
                outcomes = await execute(
                    config={"output_key": "cfg", "template": runaway},
                    context=context,
                    run=MagicMock(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="render-jinja-template-1",
                    device_sessions=MagicMock(),
                )
        finally:
            task.cancel()
        self.assertGreater(ticks, 20)
        failed = {o.name: o for o in outcomes}["failure"].context.devices["device-1"]
        self.assertEqual(failed.errors[-1].failure.kind, "resource_limit")

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

class UnexpectedErrorTextTests(unittest.IsolatedAsyncioTestCase):
    """D3: an exception the step did not raise itself keeps only its class name."""

    async def test_a_store_error_keeps_only_its_class_name_and_gets_a_record(self) -> None:
        artifacts = MagicMock()
        artifacts.store = AsyncMock(
            side_effect=RuntimeError("could not connect: password=hunter2hunter2 host=db")
        )

        outcomes = await execute(
            config={"output_key": "cfg", "template": "hostname {{ device.hostname }}"},
            context=make_context([make_device("d1")]),
            run=MagicMock(),
            artifact_service=artifacts,
            node_id="render-1",
            device_sessions=MagicMock(),
        )

        failed = next(o for o in outcomes if o.name == "failure").context.devices["d1"]
        error = failed.errors[-1]
        self.assertEqual((error.code, error.message), ("runtimeerror", "RuntimeError"))
        self.assertEqual(error.step_id, "render-jinja-template")
        self.assertIsNotNone(error.failure)
        self.assertEqual(error.failure.kind, "internal_error")


class CommandArtifactReadTests(unittest.IsolatedAsyncioTestCase):
    """W3a-15: upstream command artifacts are read only for a template that names them."""

    async def _render(self, template: str) -> tuple[int, str]:
        artifacts = InMemoryArtifactService()
        ref = await artifacts.store(
            content="Cisco IOS", kind="command_output", device_id="d1", run_id="run-1"
        )
        device = DeviceContext(
            id="d1",
            name="lab",
            hostname="lab",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
            command_results={
                "run-1": [
                    CommandResult(
                        node_id="run-1", command="show version", success=True, output_ref=ref
                    )
                ]
            },
        )
        reads: list[str] = []
        original = artifacts.resolve

        async def _counting(artifact_ref):  # noqa: ANN001, ANN202
            reads.append(artifact_ref.artifact_id)
            return await original(artifact_ref)

        with patch.object(artifacts, "resolve", _counting):
            outcomes = await execute(
                config={"output_key": "out", "template": template},
                context=WorkflowContext(
                    run_id="run-1", workflow_id="wf-1", devices={"d1": device}
                ),
                run=MagicMock(id=1),
                artifact_service=artifacts,
                node_id="render-1",
                device_sessions=MagicMock(),
            )
        entry = outcomes[0].context.devices["d1"].parsed["out"]
        rendered = await original(ArtifactRef.model_validate(entry["artifact_ref"]))
        return len(reads), rendered

    async def test_a_template_without_command_variables_reads_nothing(self) -> None:
        reads, rendered = await self._render("hostname {{ device.hostname }}")

        self.assertEqual(reads, 0)
        self.assertEqual(rendered, "hostname lab")

    async def test_each_command_variable_still_reads_the_artifacts(self) -> None:
        for template in (
            "{{ command.raw }}",
            "{{ commands[0].raw }}",
            "{{ commands_by_name['show version'].raw }}",
            "{% for c in commands %}{{ c.raw }}{% endfor %}",
        ):
            with self.subTest(template=template):
                reads, rendered = await self._render(template)
                self.assertEqual(reads, 1)
                self.assertEqual(rendered, "Cisco IOS")


class RenderJinjaTemplateStoredTemplateTests(unittest.IsolatedAsyncioTestCase):
    """The production path: the panel and the gallery write ``template_id`` (W13-08)."""

    _LOAD = "workflow_steps.render_jinja_template.executor.load_stored_template"

    def _context(self) -> WorkflowContext:
        return make_context([make_device("d1", name="lab")])

    async def _run(self, config: dict, *, stored: str | None = None):  # noqa: ANN202
        artifact_service = InMemoryArtifactService()
        with patch(self._LOAD, return_value=stored) as load:
            outcomes = await call_step(
                execute,
                {"output_key": "out", **config},
                self._context(),
                artifact_service=artifact_service,
            )
        return outcomes, artifact_service, load

    async def test_stored_template_is_loaded_by_id_and_rendered(self) -> None:
        outcomes, artifacts, load = await self._run(
            {"template_id": 7}, stored="hostname {{ device.hostname }}\n"
        )

        load.assert_called_once_with(7, step_id="render-jinja-template")
        entry = outcomes[0].context.devices["d1"].parsed["out"]
        rendered = await artifacts.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertIn("hostname lab", rendered)

    async def test_template_id_may_be_a_numeric_string(self) -> None:
        _outcomes, _artifacts, load = await self._run({"template_id": "12"}, stored="x")

        load.assert_called_once_with(12, step_id="render-jinja-template")

    async def test_non_integer_template_id_is_a_config_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "template_id must be an integer"):
            await self._run({"template_id": "abc"}, stored="x")

    async def test_empty_stored_template_is_a_config_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no content"):
            await self._run({"template_id": 7}, stored="  \n")

    async def test_an_inline_template_is_not_a_template(self) -> None:
        # W3a-09: the inline ``template`` key was compat for nodes older than the template library.
        with self.assertRaisesRegex(ValueError, "stored template must be selected"):
            await _execute(
                config={"output_key": "out", "template": "inline {{ device.hostname }}"},
                context=self._context(),
                run=MagicMock(),
                artifact_service=InMemoryArtifactService(),
                node_id="n1",
                device_sessions=MagicMock(),
            )

    async def test_nothing_selected_is_a_config_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "stored template must be selected"):
            await self._run({}, stored=None)



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
