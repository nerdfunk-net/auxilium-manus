"""Tests that StepRunner wires its DeviceSessionPool into every executor call
and that close delegates to the pool."""

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
    runner.device_sessions.close = AsyncMock()
    return runner


class StepRunnerSecretScopeTests(unittest.IsolatedAsyncioTestCase):
    def test_segment_entry_points_are_wrapped_in_a_secret_scope(self) -> None:
        # functools.wraps leaves __wrapped__ on the decorated coroutine functions.
        for name in ("execute_all", "resume_after_join", "execute_subgraph"):
            self.assertTrue(hasattr(getattr(StepRunner, name), "__wrapped__"), name)

    async def test_execute_all_runs_inside_secret_scope(self) -> None:
        from services.workflow_context import secret_fields

        seen: dict[str, object] = {}
        runner = _runner()

        async def inner(self_, *, run, workflow):
            seen["scope"] = secret_fields._RUN_SECRETS.get()
            return True

        wrapped = secret_fields.with_run_secret_scope(inner)
        self.assertTrue(await wrapped(runner, run=MagicMock(), workflow=MagicMock()))
        self.assertIsInstance(seen["scope"], set)
        self.assertIsNone(secret_fields._RUN_SECRETS.get())


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
            patch("services.execution.step_runner.runner.pre_step_guard"),
            patch("services.execution.step_runner.runner.post_step_guard"),
            patch("services.execution.step_runner.runner.effective_produces"),
            patch("services.execution.step_runner.runner.capability_spec_from_plugin"),
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


if __name__ == "__main__":
    unittest.main()
