"""log-attributes: an artifact that cannot be read is marked, the dump goes on (maintainer
decision 2026-11-27)."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock

from models.workflow_context import ArtifactRef, DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.log_attributes.executor import _METADATA_SUFFIX, execute

_LOGGER = "workflow_steps.log_attributes.executor"
_SECRET = "could not read: password=hunter2hunter2"


class _Unreadable(InMemoryArtifactService):
    """Resolves every artifact except the ones in ``broken``, which raise ``error``."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.broken: set[str] = set()
        self.error = error

    async def resolve(self, ref: ArtifactRef) -> str:
        if ref.artifact_id in self.broken:
            raise self.error
        return await super().resolve(ref)


def _rendered_entry(ref: ArtifactRef) -> dict:
    return {
        "artifact_ref": ref.model_dump(mode="json"),
        "step_node_id": "render-jinja-template-3",
        "output_key": "device_config",
        "size_bytes": 10,
        "kind": "rendered_template",
    }


async def _store(service: InMemoryArtifactService, content: str, kind: str) -> ArtifactRef:
    return await service.store(content=content, kind=kind, device_id="d", run_id="run-1")


async def _run(service: InMemoryArtifactService, context: WorkflowContext, **flags: bool):  # noqa: ANN202
    return await execute(
        config={"output_destination": "stdout", "output_format": "json", **flags},
        context=context,
        run=MagicMock(),
        artifact_service=service,
        node_id="log-attributes-5",
        device_sessions=MagicMock(),
    )


class UnreadableArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unreadable_rendered_template_is_marked_and_the_others_are_shown(self) -> None:
        service = _Unreadable(RuntimeError(_SECRET))
        good = await _store(service, "hostname ok", "rendered_template")
        bad = await _store(service, "hostname gone", "rendered_template")
        service.broken.add(bad.artifact_id)
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "d1": DeviceContext(
                    id="d1",
                    name="d1",
                    hostname="d1",
                    parsed={"device_config": _rendered_entry(good)},
                ),
                "d2": DeviceContext(
                    id="d2",
                    name="d2",
                    hostname="d2",
                    parsed={"device_config": _rendered_entry(bad)},
                ),
            },
        )

        with self.assertLogs(_LOGGER, level="WARNING") as logs:
            outcomes = await _run(service, context, show_parsed_templates=True)

        self.assertEqual(len(logs.records), 1)
        self.assertIn("device_id=d2", logs.records[0].getMessage())

        self.assertEqual([o.name for o in outcomes], ["success"])
        payload = outcomes[0].context.metadata[f"log-attributes-5{_METADATA_SUFFIX}"]
        devices = json.loads(payload["content"])["devices"]
        self.assertEqual(
            devices["d1"]["parsed"]["device_config"]["rendered_content"], "hostname ok"
        )
        self.assertEqual(
            devices["d2"]["parsed"]["device_config"]["rendered_content"],
            "<unavailable: RuntimeError>",
        )
        self.assertNotIn("hunter2", payload["content"])

    async def test_an_unreadable_startup_config_is_marked_and_the_running_config_is_shown(
        self,
    ) -> None:
        service = _Unreadable(OSError(_SECRET))
        running = await _store(service, "hostname lab\n!", "running_config")
        startup = await _store(service, "hostname old\n!", "startup_config")
        service.broken.add(startup.artifact_id)
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            running_config_ref=running,
            startup_config_ref=startup,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"d1": device})

        outcomes = await _run(service, context, show_device_configs=True)

        self.assertEqual([o.name for o in outcomes], ["success"])
        payload = outcomes[0].context.metadata[f"log-attributes-5{_METADATA_SUFFIX}"]
        snapshot = json.loads(payload["content"])["devices"]["d1"]
        self.assertEqual(snapshot["running_config_content"], "hostname lab\n!")
        self.assertEqual(snapshot["startup_config_content"], "<unavailable: OSError>")

    async def test_the_warning_names_the_device_and_class_but_not_the_text(self) -> None:
        service = _Unreadable(RuntimeError(_SECRET))
        running = await _store(service, "x", "running_config")
        service.broken.add(running.artifact_id)
        device = DeviceContext(id="d1", name="d1", hostname="d1", running_config_ref=running)
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"d1": device})

        with self.assertLogs(_LOGGER, level="DEBUG") as logs:
            await _run(service, context, show_device_configs=True)

        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("d1", warnings[0])
        self.assertIn("RuntimeError", warnings[0])
        self.assertNotIn("hunter2", warnings[0])
        self.assertTrue(any(r.levelname == "DEBUG" and r.exc_info for r in logs.records))

    async def test_a_cancelled_read_is_not_swallowed(self) -> None:
        service = _Unreadable(asyncio.CancelledError())
        running = await _store(service, "x", "running_config")
        service.broken.add(running.artifact_id)
        device = DeviceContext(id="d1", name="d1", hostname="d1", running_config_ref=running)
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"d1": device})

        with self.assertRaises(asyncio.CancelledError):
            await _run(service, context, show_device_configs=True)


if __name__ == "__main__":
    unittest.main()
