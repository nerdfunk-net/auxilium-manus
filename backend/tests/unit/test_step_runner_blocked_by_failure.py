"""Tests for the "blocked by upstream device failure" skip behaviour.

When every device that could reach a step was lost to a real upstream
failure, that step should be recorded as "skipped" (not a trivial 0/0
"success") and the run's final status should be "failed" — but only for the
branch actually affected; a step wired to the failing step's own "failure"
handle, or an unrelated branch, must still run normally. A legitimately empty
inventory match (no failure, just nothing selected) must NOT be treated as a
failure. Exercised through `_run_steps_until_fan_out_or_done`, the real
production entry point, using the same harness as
`test_debug_mode_stepping.py`.
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
from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import StepRunner


def _node(node_id: str, kind: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str, source_handle: str | None = None) -> dict[str, Any]:
    edge: dict[str, Any] = {"source": source, "target": target}
    if source_handle is not None:
        edge["sourceHandle"] = source_handle
    return edge


def _make_session() -> tuple[Session, Any]:
    engine = create_engine("sqlite:///:memory:")
    WorkflowRun.metadata.create_all(
        engine,
        tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__],
    )
    return sessionmaker(bind=engine)(), engine


def _make_run(db: Session) -> WorkflowRun:
    run = WorkflowRun(
        uuid="run-uuid-1",
        workflow_id=1,
        triggered_by_id=None,
        status="running",
        trigger_type="manual",
        run_mode="normal",
        device_ids=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id)


def _mark_failed(device: DeviceContext, node_id: str) -> DeviceContext:
    error = DeviceError(node_id=node_id, step_id="run-command", code="boom", message="boom")
    return device.model_copy(update={"errors": [error]})


def _fail_all_devices_outcomes(node_id: str, context: WorkflowContext) -> list[StepOutcome]:
    """Simulate a step that fails for every device it received."""
    failed = {did: _mark_failed(dc, node_id) for did, dc in context.devices.items()}
    return [
        StepOutcome(name="success", context=context.model_copy(update={"devices": {}})),
        StepOutcome(name="failure", context=context.model_copy(update={"devices": failed})),
    ]


class BlockedByUpstreamFailureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)

    def _step_results_for(self, run_id: int) -> dict[str, WorkflowStepResult]:
        return {r.step_node_id: r for r in self.run_repo.get_step_results_for_run(run_id)}

    async def test_downstream_step_skipped_when_all_devices_fail(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("fails_all", "run-command"),
            _node("downstream", "run-command"),
        ]
        edges = [_edge("inv", "fails_all"), _edge("fails_all", "downstream")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()
        called_nodes: list[str] = []

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            called_nodes.append(node_id)
            if node_id == "inv":
                devices = {"d1": _device("d1"), "d2": _device("d2")}
                success_ctx = context.model_copy(update={"devices": devices})
                return [StepOutcome(name="success", context=success_ctx)]
            if node_id == "fails_all":
                return _fail_all_devices_outcomes(node_id, context)
            raise AssertionError(f"{node_id!r} should have been skipped, not executed")

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertEqual(called_nodes, ["inv", "fails_all"])
        self.assertEqual(final_status, "failed")

        results = self._step_results_for(run.id)
        self.assertEqual(results["inv"].status, "success")
        self.assertEqual(results["fails_all"].status, "failed")
        self.assertEqual(results["downstream"].status, "skipped")

    async def test_empty_inventory_match_is_not_treated_as_failure(self) -> None:
        nodes = [_node("inv", "get-nautobot-devices"), _node("downstream", "run-command")]
        edges = [_edge("inv", "downstream")]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()
        called_nodes: list[str] = []

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            called_nodes.append(node_id)
            # Both the inventory step and a device-requiring step downstream
            # of it behave like real executors: 0 devices in -> trivial
            # success out, no failure outcome at all (nothing errored).
            return [StepOutcome(name="success", context=context)]

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        # downstream actually ran (not skipped) even though its input was empty.
        self.assertEqual(called_nodes, ["inv", "downstream"])
        self.assertEqual(final_status, "success")

        results = self._step_results_for(run.id)
        self.assertEqual(results["inv"].status, "success")
        self.assertEqual(results["downstream"].status, "success")

    async def test_failure_handle_branch_still_runs_when_success_branch_is_blocked(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("fails_all", "run-command"),
            _node("on_success", "run-command"),
            _node("on_failure", "run-command"),
        ]
        edges = [
            _edge("inv", "fails_all"),
            _edge("fails_all", "on_success", source_handle="success"),
            _edge("fails_all", "on_failure", source_handle="failure"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()
        called_nodes: list[str] = []

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            called_nodes.append(node_id)
            if node_id == "inv":
                devices = {"d1": _device("d1")}
                success_ctx = context.model_copy(update={"devices": devices})
                return [StepOutcome(name="success", context=success_ctx)]
            if node_id == "fails_all":
                return _fail_all_devices_outcomes(node_id, context)
            # on_success / on_failure: whatever devices reached them, trivially succeed.
            return [StepOutcome(name="success", context=context)]

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertIn("on_failure", called_nodes)
        self.assertNotIn("on_success", called_nodes)
        self.assertEqual(final_status, "failed")

        results = self._step_results_for(run.id)
        self.assertEqual(results["on_success"].status, "skipped")
        self.assertEqual(results["on_failure"].status, "success")


class BlockedByUpstreamFailureHelperTests(unittest.TestCase):
    """Direct unit tests for the pure `_blocked_by_upstream_failure` check."""

    def test_no_parent_edges_is_never_blocked(self) -> None:
        self.assertFalse(StepRunner._blocked_by_upstream_failure("n1", [], {}, set()))

    def test_blocked_when_parent_already_blocked(self) -> None:
        edges = [_edge("a", "b")]
        self.assertTrue(StepRunner._blocked_by_upstream_failure("b", edges, {}, {"a"}))

    def test_not_blocked_when_parent_delivers_devices(self) -> None:
        edges = [_edge("a", "b")]
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        step_outcomes = {"a": {"success": ctx}}
        self.assertFalse(StepRunner._blocked_by_upstream_failure("b", edges, step_outcomes, set()))

    def test_blocked_when_parent_failure_outcome_has_devices(self) -> None:
        edges = [_edge("a", "b")]
        empty_success = WorkflowContext(run_id="r", workflow_id="w", devices={})
        failure_ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        step_outcomes = {"a": {"success": empty_success, "failure": failure_ctx}}
        self.assertTrue(StepRunner._blocked_by_upstream_failure("b", edges, step_outcomes, set()))

    def test_not_blocked_when_parent_has_no_outcomes_at_all(self) -> None:
        edges = [_edge("a", "b")]
        self.assertFalse(StepRunner._blocked_by_upstream_failure("b", edges, {}, set()))


if __name__ == "__main__":
    unittest.main()
