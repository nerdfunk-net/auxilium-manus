"""Tests that StepRunner wires its DeviceSessionPool into every executor call
and that suspend/close delegate to the pool (see doc/DURABLE_SSH_SESSION.md §5.4)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import StepOutcome, WorkflowContext
from services.execution.step_runner import StepRunner


def _runner() -> StepRunner:
    runner = StepRunner.__new__(StepRunner)
    runner.plugin_registry = MagicMock()
    runner.artifact_service = MagicMock()
    runner.device_sessions = MagicMock()
    runner.device_sessions.suspend = AsyncMock()
    runner.device_sessions.close = AsyncMock()
    return runner


class StepRunnerDeviceSessionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_step_passes_device_sessions_to_executor(self) -> None:
        runner = _runner()
        plugin = MagicMock()
        plugin.executable = True
        runner.plugin_registry.get_plugin.return_value = plugin
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")

        captured: dict[str, object] = {}

        async def _fake_executor(**kwargs: object) -> list[StepOutcome]:
            captured.update(kwargs)
            return [StepOutcome(name="success", context=context)]

        with (
            patch(
                "services.execution.step_registry.STEP_REGISTRY", {"noop": _fake_executor}
            ),
            patch("services.execution.step_runner.pre_step_guard"),
            patch("services.execution.step_runner.post_step_guard"),
            patch("services.execution.step_runner.effective_produces"),
            patch("services.execution.step_runner.capability_spec_from_plugin"),
        ):
            await runner._execute_step(
                step_type="noop",
                config={},
                context=context,
                run=MagicMock(id=1),
                node_id="n1",
            )

        self.assertIs(captured["device_sessions"], runner.device_sessions)

    async def test_close_device_sessions_delegates_to_pool(self) -> None:
        runner = _runner()
        await runner.close_device_sessions()
        runner.device_sessions.close.assert_awaited_once()

    async def test_suspend_device_sessions_delegates_to_pool(self) -> None:
        runner = _runner()
        await runner.suspend_device_sessions()
        runner.device_sessions.suspend.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
