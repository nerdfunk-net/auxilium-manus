"""Tests for the get-catalyst-center-configs executor (mocked service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.catalyst_center.common.exceptions import CatalystCenterAPIError
from workflow_steps.get_catalyst_center_configs.executor import execute

MODULE = "workflow_steps.get_catalyst_center_configs.executor"


def _device(device_id: str, *, source: str = "catalyst_center") -> DeviceContext:
    return DeviceContext(
        id=device_id, name=device_id, hostname=device_id, source=source, source_id="lab"
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


class _Harness:
    def __init__(self, get_device_config):
        self.command_service = MagicMock()
        self.command_service.get_device_config = get_device_config

    def __enter__(self):
        self._patches = [
            patch(f"{MODULE}.object_session", return_value=MagicMock()),
            patch(
                "service_factory.build_catalyst_center_source_config_service",
                return_value=MagicMock(),
            ),
            patch(
                "service_factory.build_catalyst_center_command_service",
                return_value=self.command_service,
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(context: WorkflowContext, artifacts=None):
    run = MagicMock()
    run.id = 1
    return await execute(
        config={},
        context=context,
        run=run,
        artifact_service=artifacts or InMemoryArtifactService(),
        node_id="node-1",
        device_sessions=MagicMock(),
    )


class GetCatalystCenterConfigsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_running_config_and_adds_capability(self) -> None:
        artifacts = InMemoryArtifactService()
        with _Harness(AsyncMock(return_value="hostname sw1\n!")):
            outcomes = await _run(_context(_device("a")), artifacts)

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["a"]
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertIn(Capability.RUNNING_CONFIG, device.capabilities)
        self.assertEqual(await artifacts.resolve(device.running_config_ref), "hostname sw1\n!")

    async def test_failed_device_goes_to_failure_outcome_only(self) -> None:
        async def fetch(device_id: str) -> str:
            if device_id == "b":
                raise CatalystCenterAPIError("boom")
            return "cfg"

        with _Harness(AsyncMock(side_effect=fetch)):
            outcomes = await _run(_context(_device("a"), _device("b")))

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name["success"].context.devices), {"a"})
        self.assertEqual(set(by_name["failure"].context.devices), {"b"})
        self.assertEqual(
            by_name["failure"].context.devices["b"].errors[0].code, "catalyst_center_error"
        )

    async def test_non_catalyst_device_is_rejected_without_a_request(self) -> None:
        get_config = AsyncMock(return_value="cfg")
        with _Harness(get_config):
            outcomes = await _run(_context(_device("n", source="nautobot")))
        failure = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(failure.context.devices["n"].errors[0].code, "not_catalyst_center_device")
        get_config.assert_not_awaited()

    async def test_no_devices_is_a_noop_success(self) -> None:
        with _Harness(AsyncMock()):
            outcomes = await _run(_context())
        self.assertEqual([o.name for o in outcomes], ["success"])
