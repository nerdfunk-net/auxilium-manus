"""Tests for step-by-step Debug mode: the per-node wait_for gate and its
interaction with the atomic fan-out step.

These exercise `_run_steps_until_fan_out_or_done` (the plain async helper
`hatchet/workflows/workflow_run.py` factors the durable per-node loop into)
against a real in-memory SQLite-backed `WorkflowRun`/`WorkflowStepResult`
session, with `StepRunner._execute_step` stubbed so the tests focus purely on
the pause/resume orchestration rather than individual step executors (already
covered by the other `tests/test_*_executor.py` files).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from hatchet.workflows.workflow_run import _run_steps_until_fan_out_or_done
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import StepRunner


def _node(node_id: str, kind: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str, source_handle: str | None = None) -> dict[str, Any]:
    edge: dict[str, Any] = {"source": source, "target": target}
    if source_handle is not None:
        edge["sourceHandle"] = source_handle
    return edge


LINEAR_NODES = [_node("n1", "noop"), _node("n2", "noop"), _node("n3", "noop")]
LINEAR_EDGES = [_edge("n1", "n2"), _edge("n2", "n3")]

FAN_OUT_NODES = [
    _node("inv", "get-nautobot-devices"),
    _node("a", "run-command"),
    _node("join", "fan-in"),
    _node("store", "store-artifact"),
]
FAN_OUT_EDGES = [_edge("inv", "a"), _edge("a", "join"), _edge("join", "store")]


def _make_session() -> tuple[Session, Any]:
    engine = create_engine("sqlite:///:memory:")
    WorkflowRun.metadata.create_all(
        engine,
        tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__],
    )
    return sessionmaker(bind=engine)(), engine


def _make_run(db: Session, *, run_mode: str) -> WorkflowRun:
    run = WorkflowRun(
        uuid="run-uuid-1",
        workflow_id=1,
        triggered_by_id=None,
        status="running",
        trigger_type="manual",
        run_mode=run_mode,
        device_ids=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def _noop_success_step(**kwargs: Any) -> list[StepOutcome]:
    context: WorkflowContext = kwargs["context"]
    return [StepOutcome(name="success", context=context)]


async def _fan_out_inventory_step(**kwargs: Any) -> list[StepOutcome]:
    context: WorkflowContext = kwargs["context"]
    fan_out_meta = {"enabled": True, "mode": "per_device"}
    fanned_out = context.model_copy(
        update={"metadata": {**context.metadata, "_fan_out": fan_out_meta}}
    )
    return [StepOutcome(name="success", context=fanned_out)]


class DebugSteppingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)
        self.wf = SimpleNamespace(id=1, canvas_nodes=LINEAR_NODES, canvas_edges=LINEAR_EDGES)

    def _step_results_for(self, run_id: int) -> list[WorkflowStepResult]:
        return self.run_repo.get_step_results_for_run(run_id)

    async def test_normal_mode_runs_straight_through_without_pausing(self) -> None:
        run = _make_run(self.db, run_mode="normal")
        ctx = AsyncMock()

        with patch.object(StepRunner, "_execute_step", side_effect=_noop_success_step):
            final_status, fan_out, returned_run = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=self.wf, ctx=ctx
            )

        self.assertEqual(final_status, "success")
        self.assertIsNone(fan_out)
        self.assertEqual(returned_run.run_mode, "normal")
        ctx.aio_wait_for_event.assert_not_called()

        results = {r.step_node_id: r for r in self._step_results_for(run.id)}
        self.assertEqual({r.status for r in results.values()}, {"success"})

    async def test_debug_mode_pauses_before_every_node_in_order(self) -> None:
        run = _make_run(self.db, run_mode="debug")
        ctx = AsyncMock()

        with patch.object(StepRunner, "_execute_step", side_effect=_noop_success_step):
            final_status, fan_out, returned_run = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=self.wf, ctx=ctx
            )

        self.assertEqual(final_status, "success")
        self.assertIsNone(fan_out)

        expected_keys = [f"workflow-run.run-uuid-1.step.{nid}" for nid in ("n1", "n2", "n3")]
        actual_keys = [call.args[0] for call in ctx.aio_wait_for_event.await_args_list]
        self.assertEqual(actual_keys, expected_keys)

        results = {r.step_node_id: r for r in self._step_results_for(run.id)}
        self.assertEqual({r.status for r in results.values()}, {"success"})
        self.assertIsNotNone(returned_run.debug_message)

    async def test_run_to_completion_stops_pausing_after_the_current_step(self) -> None:
        run = _make_run(self.db, run_mode="debug")
        ctx = AsyncMock()
        pause_count = 0

        async def _wait_for_event(_event_key: str) -> dict[str, Any]:
            nonlocal pause_count
            pause_count += 1
            if pause_count == 1:
                # Simulate RunService.continue_run() flipping run_mode mid-wait.
                run.run_mode = "normal"
                self.db.commit()
            return {}

        ctx.aio_wait_for_event.side_effect = _wait_for_event

        with patch.object(StepRunner, "_execute_step", side_effect=_noop_success_step):
            final_status, fan_out, returned_run = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=self.wf, ctx=ctx
            )

        self.assertEqual(final_status, "success")
        self.assertIsNone(fan_out)
        self.assertEqual(returned_run.run_mode, "normal")
        # Only the first node paused; n2/n3 ran straight through.
        self.assertEqual(ctx.aio_wait_for_event.await_count, 1)

        results = {r.step_node_id: r for r in self._step_results_for(run.id)}
        self.assertEqual({r.status for r in results.values()}, {"success"})

    async def test_debug_mode_pauses_once_before_fan_out_dispatch(self) -> None:
        run = _make_run(self.db, run_mode="debug")
        wf = SimpleNamespace(id=1, canvas_nodes=FAN_OUT_NODES, canvas_edges=FAN_OUT_EDGES)
        ctx = AsyncMock()

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            if kwargs["step_type"] == "get-nautobot-devices":
                return await _fan_out_inventory_step(**kwargs)
            return await _noop_success_step(**kwargs)

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, returned_run = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(final_status)
        self.assertIsNotNone(fan_out)
        self.assertEqual(fan_out["signal"].inventory_node_id, "inv")
        self.assertEqual(fan_out["signal"].join_node_id, "join")

        # Exactly one pause happened: before the inventory node itself. The
        # second, fan-out-block pause (before dispatching children) is added
        # by execute_steps() around _dispatch_children/_aggregate_and_persist,
        # not inside this helper — covered by manual E2E per the debug-mode
        # implementation plan.
        self.assertEqual(ctx.aio_wait_for_event.await_count, 1)
        self.assertEqual(
            ctx.aio_wait_for_event.await_args_list[0].args[0],
            "workflow-run.run-uuid-1.step.inv",
        )
        self.assertEqual(returned_run.status, "running")


if __name__ == "__main__":
    unittest.main()
