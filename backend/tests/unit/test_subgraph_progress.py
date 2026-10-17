"""Fan-out child progress reporting from ``run_subgraph``.

Children write no WorkflowStepResult rows; instead they report per-node state
through a progress sink so the UI can show which step each device group is on.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import StepRunner
from services.execution.step_runner.progress import DeviceGroupProgressSink


def _node(node_id: str, kind: str = "run-command") -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target}


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id)


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def node_started(self, node_id: str) -> None:
        self.events.append((node_id, "running"))

    async def node_finished(self, node_id: str, state: str) -> None:
        self.events.append((node_id, state))


class _ExplodingSink:
    async def node_started(self, node_id: str) -> None:
        raise RuntimeError("sink is down")

    async def node_finished(self, node_id: str, state: str) -> None:
        raise RuntimeError("sink is down")


class RunSubgraphProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowRunDeviceGroup.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db: Session = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        run = WorkflowRun(
            uuid="run-uuid-1",
            workflow_id=1,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        self.db.add(run)
        self.db.commit()
        self.run = run
        self.runner = StepRunner(self.db)
        self.context = WorkflowContext(
            run_id=run.uuid, workflow_id="1", devices={"d1": _device("d1")}
        )

    def _wf(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Any:
        return SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)

    async def _walk(self, wf: Any, allowed: set[str], progress: Any, stub: Any) -> Any:
        with patch.object(StepRunner, "_execute_step", side_effect=stub):
            return await self.runner.execute_subgraph(
                run=self.run,
                workflow=wf,
                initial_context=self.context,
                inventory_node_id="inv",
                allowed_node_ids=allowed,
                progress=progress,
            )

    async def test_reports_running_then_success_for_each_node_in_order(self) -> None:
        wf = self._wf([_node("inv"), _node("a"), _node("b")], [_edge("inv", "a"), _edge("a", "b")])
        sink = _RecordingSink()

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            return [StepOutcome(name="success", context=kwargs["context"])]

        await self._walk(wf, {"a", "b"}, sink, stub)

        self.assertEqual(
            sink.events,
            [("a", "running"), ("a", "success"), ("b", "running"), ("b", "success")],
        )

    async def test_reports_failed_when_executor_raises(self) -> None:
        wf = self._wf([_node("inv"), _node("a")], [_edge("inv", "a")])
        sink = _RecordingSink()

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            raise RuntimeError("device unreachable")

        _, step_errors = await self._walk(wf, {"a"}, sink, stub)

        self.assertIn("a", step_errors)
        self.assertEqual(sink.events, [("a", "running"), ("a", "failed")])

    async def test_reports_failed_when_every_device_failed_without_raising(self) -> None:
        wf = self._wf([_node("inv"), _node("a")], [_edge("inv", "a")])
        sink = _RecordingSink()

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            ctx: WorkflowContext = kwargs["context"]
            err = DeviceError(node_id="a", step_id="run-command", code="x", message="x")
            failed = _device("d1").model_copy(update={"errors": [err]})
            return [
                StepOutcome(
                    name="failure", context=ctx.model_copy(update={"devices": {"d1": failed}})
                )
            ]

        await self._walk(wf, {"a"}, sink, stub)

        self.assertEqual(sink.events, [("a", "running"), ("a", "failed")])

    async def test_reports_skipped_when_blocked_by_upstream_failure(self) -> None:
        wf = self._wf([_node("inv"), _node("a"), _node("b")], [_edge("inv", "a"), _edge("a", "b")])
        sink = _RecordingSink()

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            ctx: WorkflowContext = kwargs["context"]
            err = DeviceError(node_id="a", step_id="run-command", code="x", message="x")
            failed = _device("d1").model_copy(update={"errors": [err]})
            return [
                StepOutcome(
                    name="failure", context=ctx.model_copy(update={"devices": {"d1": failed}})
                )
            ]

        with patch.object(StepRunner, "_step_requires_devices", return_value=True):
            await self._walk(wf, {"a", "b"}, sink, stub)

        self.assertIn(("b", "skipped"), sink.events)
        self.assertNotIn(("b", "running"), sink.events)

    async def test_raising_node_skips_remaining_waves(self) -> None:
        # C1-09: once a node raised in this child, later waves do not run (hard stop).
        wf = self._wf(
            [_node("inv"), _node("a"), _node("b"), _node("c")],
            [_edge("inv", "a"), _edge("a", "b"), _edge("b", "c")],
        )
        sink = _RecordingSink()
        called: list[str] = []

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            called.append(kwargs["node_id"])
            if kwargs["node_id"] == "b":
                raise RuntimeError("boom")
            return [StepOutcome(name="success", context=kwargs["context"])]

        _, step_errors = await self._walk(wf, {"a", "b", "c"}, sink, stub)

        self.assertEqual(called, ["a", "b"])
        self.assertIn("b", step_errors)
        self.assertIn(("c", "skipped"), sink.events)
        self.assertNotIn(("c", "running"), sink.events)

    async def test_strict_mode_detects_mutating_executor(self) -> None:
        from unittest.mock import MagicMock

        context = self.context.model_copy(deep=True)

        async def mutating(**kwargs: Any) -> list[StepOutcome]:
            kwargs["context"].devices["d1"].parsed["x"] = 1
            return [StepOutcome(name="success", context=kwargs["context"])]

        plugin = MagicMock()
        with (
            patch.dict("os.environ", {"MANUS_STRICT_CONTEXT": "1"}),
            patch.dict("services.execution.step_registry.STEP_REGISTRY", {"mutator": mutating}),
            patch.object(self.runner.plugin_registry, "get_plugin", return_value=plugin),
            patch("services.execution.step_runner.runner.capability_spec_from_plugin"),
            patch("services.execution.step_runner.runner.pre_step_guard"),
            patch("services.execution.step_runner.runner.post_step_guard", new=MagicMock()),
            patch("services.execution.step_runner.runner.effective_produces"),
        ):
            with self.assertRaisesRegex(RuntimeError, "mutated its input context"):
                await self.runner._execute_step(
                    step_type="mutator",
                    config={},
                    context=context,
                    run=self.run,
                    node_id="n1",
                )

    async def test_failing_sink_never_breaks_the_walk(self) -> None:
        wf = self._wf([_node("inv"), _node("a")], [_edge("inv", "a")])

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            return [StepOutcome(name="success", context=kwargs["context"])]

        step_outcomes, step_errors = await self._walk(wf, {"a"}, _ExplodingSink(), stub)

        self.assertEqual(step_errors, {})
        self.assertIn("a", step_outcomes)

    async def test_progress_is_optional(self) -> None:
        wf = self._wf([_node("inv"), _node("a")], [_edge("inv", "a")])

        async def stub(**kwargs: Any) -> list[StepOutcome]:
            return [StepOutcome(name="success", context=kwargs["context"])]

        step_outcomes, _ = await self._walk(wf, {"a"}, None, stub)

        self.assertIn("a", step_outcomes)


class DeviceGroupProgressSinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowRunDeviceGroup.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.repo = RunRepository(self.db)
        run = WorkflowRun(
            uuid="run-uuid-1",
            workflow_id=1,
            triggered_by_id=None,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        self.db.add(run)
        self.db.commit()
        self.run_id = run.id
        self.repo.create_device_groups(run_id=self.run_id, groups=[(3, ["r1"])])

    async def test_persists_node_states_to_the_group_row(self) -> None:
        sink = DeviceGroupProgressSink(self.repo, run_id=self.run_id, child_index=3)

        await sink.node_started("a")
        self.assertEqual(self.repo.list_device_groups(self.run_id)[0].node_states, {"a": "running"})
        await sink.node_finished("a", "success")

        self.assertEqual(self.repo.list_device_groups(self.run_id)[0].node_states, {"a": "success"})

    async def test_concurrent_writes_are_serialised_and_all_land(self) -> None:
        sink = DeviceGroupProgressSink(self.repo, run_id=self.run_id, child_index=3)

        await asyncio.gather(*(sink.node_started(f"n{i}") for i in range(5)))

        states = self.repo.list_device_groups(self.run_id)[0].node_states
        self.assertEqual(states, {f"n{i}": "running" for i in range(5)})

    async def test_overall_status_reflects_worst_node_state(self) -> None:
        sink = DeviceGroupProgressSink(self.repo, run_id=self.run_id, child_index=3)
        self.assertEqual(sink.overall_status(), "success")

        await sink.node_finished("a", "success")
        await sink.node_finished("b", "skipped")
        self.assertEqual(sink.overall_status(), "success")

        await sink.node_finished("c", "partial")
        self.assertEqual(sink.overall_status(), "partial")

        await sink.node_finished("d", "failed")
        self.assertEqual(sink.overall_status(), "failed")

    async def test_swallows_repository_errors(self) -> None:
        sink = DeviceGroupProgressSink(self.repo, run_id=self.run_id, child_index=3)
        with patch.object(
            RunRepository, "set_device_group_node_state", side_effect=RuntimeError("db gone")
        ):
            await sink.node_started("a")  # must not raise


if __name__ == "__main__":
    unittest.main()
