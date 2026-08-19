"""Tests for the funnel canvas node: StepRunner._resolve_funnels splices a
funnel out of the graph before execution, rewiring every incoming edge
straight to the funnel's one downstream target while preserving the
original edge's sourceHandle (outcome name) — so e.g. several steps'
``failure`` handles funneled into Notify On Error still read as failure
edges, and execution behaves exactly as if every source had wired to the
destination directly.
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


def _edge(
    source: str,
    target: str,
    source_handle: str | None = None,
    target_handle: str | None = None,
) -> dict[str, Any]:
    edge: dict[str, Any] = {"source": source, "target": target}
    if source_handle is not None:
        edge["sourceHandle"] = source_handle
    if target_handle is not None:
        edge["targetHandle"] = target_handle
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
    failed = {did: _mark_failed(dc, node_id) for did, dc in context.devices.items()}
    return [
        StepOutcome(name="success", context=context.model_copy(update={"devices": {}})),
        StepOutcome(name="failure", context=context.model_copy(update={"devices": failed})),
    ]


class ResolveFunnelsPureTests(unittest.TestCase):
    """Direct unit tests for the pure `_resolve_funnels` splice."""

    def test_no_funnel_returns_graph_unchanged(self) -> None:
        nodes = [_node("a", "run-command"), _node("b", "run-command")]
        edges = [_edge("a", "b")]
        resolved_nodes, resolved_edges = StepRunner._resolve_funnels(nodes, edges)
        self.assertEqual(resolved_nodes, nodes)
        self.assertEqual(resolved_edges, edges)

    def test_many_sources_spliced_to_one_target_preserving_source_handle(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("b", "run-command"),
            _node("funnel1", "funnel"),
            _node("sink", "notify-on-error"),
        ]
        edges = [
            _edge("a", "funnel1", source_handle="failure"),
            _edge("b", "funnel1", source_handle="failure"),
            _edge("funnel1", "sink", target_handle="input"),
        ]
        resolved_nodes, resolved_edges = StepRunner._resolve_funnels(nodes, edges)

        resolved_ids = {n["id"] for n in resolved_nodes}
        self.assertNotIn("funnel1", resolved_ids)
        self.assertEqual(resolved_ids, {"a", "b", "sink"})

        by_source = {e["source"]: e for e in resolved_edges}
        self.assertEqual(len(resolved_edges), 2)
        self.assertEqual(by_source["a"]["target"], "sink")
        self.assertEqual(by_source["a"]["sourceHandle"], "failure")
        self.assertEqual(by_source["a"]["targetHandle"], "input")
        self.assertEqual(by_source["b"]["target"], "sink")
        self.assertEqual(by_source["b"]["sourceHandle"], "failure")
        self.assertEqual(by_source["b"]["targetHandle"], "input")

    def test_funnel_with_no_outgoing_edge_raises(self) -> None:
        nodes = [_node("a", "run-command"), _node("funnel1", "funnel")]
        edges = [_edge("a", "funnel1")]
        with self.assertRaises(ValueError):
            StepRunner._resolve_funnels(nodes, edges)

    def test_funnel_with_multiple_outgoing_edges_raises(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("funnel1", "funnel"),
            _node("sink1", "run-command"),
            _node("sink2", "run-command"),
        ]
        edges = [
            _edge("a", "funnel1"),
            _edge("funnel1", "sink1"),
            _edge("funnel1", "sink2"),
        ]
        with self.assertRaises(ValueError):
            StepRunner._resolve_funnels(nodes, edges)

    def test_funnel_chained_into_another_funnel_raises(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("funnel1", "funnel"),
            _node("funnel2", "funnel"),
            _node("sink", "run-command"),
        ]
        edges = [
            _edge("a", "funnel1"),
            _edge("funnel1", "funnel2"),
            _edge("funnel2", "sink"),
        ]
        with self.assertRaises(ValueError):
            StepRunner._resolve_funnels(nodes, edges)


class FunnelExecutionTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end: a funnel feeding Notify-On-Error via the real production
    entry point (`_run_steps_until_fan_out_or_done`) behaves identically to
    direct wiring — the shared sink still runs once with the union of both
    failing branches' devices."""

    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)

    def _step_results_for(self, run_id: int) -> dict[str, WorkflowStepResult]:
        return {r.step_node_id: r for r in self.run_repo.get_step_results_for_run(run_id)}

    async def test_funnel_feeding_shared_sink_matches_direct_wiring(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("fails_a", "run-command"),
            _node("fails_b", "run-command"),
            _node("funnel1", "funnel"),
            _node("sink", "run-command"),
        ]
        edges = [
            _edge("inv", "fails_a"),
            _edge("inv", "fails_b"),
            _edge("fails_a", "funnel1", source_handle="failure"),
            _edge("fails_b", "funnel1", source_handle="failure"),
            _edge("funnel1", "sink", target_handle="input"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()
        called_nodes: list[str] = []
        sink_devices: dict[str, DeviceContext] = {}

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            called_nodes.append(node_id)
            if node_id == "inv":
                devices = {"d1": _device("d1"), "d2": _device("d2")}
                success_ctx = context.model_copy(update={"devices": devices})
                return [StepOutcome(name="success", context=success_ctx)]
            if node_id in ("fails_a", "fails_b"):
                return _fail_all_devices_outcomes(node_id, context)
            if node_id == "sink":
                sink_devices.update(context.devices)
                return [StepOutcome(name="success", context=context)]
            raise AssertionError(f"unexpected node {node_id!r}, funnel should not execute")

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertNotIn("funnel1", called_nodes)
        self.assertEqual(called_nodes.count("sink"), 1)
        self.assertEqual(final_status, "failed")

        results = self._step_results_for(run.id)
        self.assertNotIn("funnel1", results)
        self.assertEqual(set(sink_devices), {"d1", "d2"})
        for device in sink_devices.values():
            node_ids = {error.node_id for error in device.errors}
            self.assertEqual(node_ids, {"fails_a", "fails_b"})


if __name__ == "__main__":
    unittest.main()
