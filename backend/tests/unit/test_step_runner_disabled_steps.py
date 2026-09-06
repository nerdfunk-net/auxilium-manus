"""Tests for author-disabled steps: StepRunner._resolve_disabled_steps splices
a step flagged ``data.disabled: true`` out of the graph before execution.

Two shapes, one rule:
  * a disabled step with no connections is dropped ("parked");
  * a disabled step wired between neighbours is removed and every inbound edge
    is rewired straight to the next enabled step, walking through chains of
    disabled steps, preserving the upstream edge's sourceHandle and carrying
    the far edge's targetHandle — so execution behaves as if the disabled
    step(s) were never there.
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
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from repositories.run_repository import RunRepository
from services.execution.step_runner import StepRunner


def _node(node_id: str, kind: str, *, disabled: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {"kind": kind, "title": kind}
    if disabled:
        data["disabled"] = True
    return {"id": node_id, "data": data}


def _edge(
    source: str,
    target: str,
    source_handle: str | None = None,
    target_handle: str | None = None,
) -> dict[str, Any]:
    edge: dict[str, Any] = {"id": f"{source}->{target}", "source": source, "target": target}
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


class ResolveDisabledStepsPureTests(unittest.TestCase):
    """Direct unit tests for the pure `_resolve_disabled_steps` splice."""

    def test_no_disabled_returns_graph_unchanged(self) -> None:
        nodes = [_node("a", "run-command"), _node("b", "run-command")]
        edges = [_edge("a", "b")]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)
        self.assertEqual(resolved_nodes, nodes)
        self.assertEqual(resolved_edges, edges)

    def test_parked_disabled_step_is_dropped_without_touching_other_edges(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("b", "run-command"),
            _node("parked", "run-command", disabled=True),
        ]
        edges = [_edge("a", "b")]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertEqual({n["id"] for n in resolved_nodes}, {"a", "b"})
        self.assertEqual(resolved_edges, edges)

    def test_mid_chain_step_is_bypassed_preserving_handles(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("x", "run-command", disabled=True),
            _node("b", "run-command"),
        ]
        edges = [
            _edge("a", "x", source_handle="failure"),
            _edge("x", "b", target_handle="input"),
        ]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertEqual({n["id"] for n in resolved_nodes}, {"a", "b"})
        self.assertEqual(len(resolved_edges), 1)
        wire = resolved_edges[0]
        self.assertEqual(wire["source"], "a")
        self.assertEqual(wire["target"], "b")
        self.assertEqual(wire["sourceHandle"], "failure")
        self.assertEqual(wire["targetHandle"], "input")

    def test_chain_of_disabled_steps_collapses(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("x", "run-command", disabled=True),
            _node("y", "run-command", disabled=True),
            _node("b", "run-command"),
        ]
        edges = [
            _edge("a", "x", source_handle="success"),
            _edge("x", "y"),
            _edge("y", "b", target_handle="input"),
        ]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertEqual({n["id"] for n in resolved_nodes}, {"a", "b"})
        self.assertEqual(len(resolved_edges), 1)
        self.assertEqual(resolved_edges[0]["source"], "a")
        self.assertEqual(resolved_edges[0]["target"], "b")
        self.assertEqual(resolved_edges[0]["sourceHandle"], "success")
        self.assertEqual(resolved_edges[0]["targetHandle"], "input")

    def test_multiple_inbound_edges_all_rewired(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("c", "run-command"),
            _node("x", "run-command", disabled=True),
            _node("b", "run-command"),
        ]
        edges = [
            _edge("a", "x", source_handle="success"),
            _edge("c", "x", source_handle="failure"),
            _edge("x", "b", target_handle="input"),
        ]
        _, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        wires = {(e["source"], e["sourceHandle"], e["target"]) for e in resolved_edges}
        self.assertEqual(wires, {("a", "success", "b"), ("c", "failure", "b")})

    def test_multiple_outbound_edges_fan_to_every_downstream(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("x", "run-command", disabled=True),
            _node("b", "run-command"),
            _node("c", "run-command"),
        ]
        edges = [
            _edge("a", "x", source_handle="success"),
            _edge("x", "b"),
            _edge("x", "c"),
        ]
        _, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        targets = {e["target"] for e in resolved_edges}
        self.assertEqual(targets, {"b", "c"})
        self.assertTrue(all(e["source"] == "a" for e in resolved_edges))

    def test_cycle_among_disabled_steps_does_not_recurse_forever(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("x", "run-command", disabled=True),
            _node("y", "run-command", disabled=True),
        ]
        edges = [
            _edge("a", "x"),
            _edge("x", "y"),
            _edge("y", "x"),
        ]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertEqual({n["id"] for n in resolved_nodes}, {"a"})
        # No enabled node lies beyond the disabled cycle, so nothing is rewired.
        self.assertEqual(resolved_edges, [])

    def test_disabled_step_with_no_outbound_drops_inbound_edge(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("x", "run-command", disabled=True),
        ]
        edges = [_edge("a", "x")]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertEqual({n["id"] for n in resolved_nodes}, {"a"})
        self.assertEqual(resolved_edges, [])

    def test_branching_disabled_step_only_passes_success_through(self) -> None:
        """A disabled step's failure/error branch must not fire on success."""
        nodes = [
            _node("a", "run-command"),
            _node("x", "run-command", disabled=True),
            _node("ok", "run-command"),
            _node("alert", "notify-on-error"),
        ]
        edges = [
            _edge("a", "x", source_handle="success"),
            _edge("x", "ok", source_handle="success"),
            _edge("x", "alert", source_handle="failure"),
        ]
        _, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        targets = {e["target"] for e in resolved_edges}
        self.assertEqual(targets, {"ok"})
        self.assertNotIn("alert", targets)

    def test_lone_outgoing_edge_is_followed_regardless_of_handle(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("x", "route-on-attribute", disabled=True),
            _node("b", "run-command"),
        ]
        edges = [
            _edge("a", "x", source_handle="success"),
            _edge("x", "b", source_handle="route-a"),
        ]
        _, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertEqual([e["target"] for e in resolved_edges], ["b"])

    def test_fan_in_node_ignores_disabled_flag(self) -> None:
        """A fan-in is graph structure — disabling it must not splice it out."""
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("join", "fan-in", disabled=True),
            _node("after", "run-command"),
        ]
        edges = [_edge("inv", "join"), _edge("join", "after")]
        resolved_nodes, resolved_edges = StepRunner._resolve_disabled_steps(nodes, edges)

        self.assertIn("join", {n["id"] for n in resolved_nodes})
        self.assertEqual(len(resolved_edges), 2)


class DisabledPlusFunnelResolutionTests(unittest.TestCase):
    """`load_execution_graph` resolves funnels before disabled steps, so a
    disabled step near a funnel can never leave the funnel malformed."""

    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.runner = StepRunner(self.db)

    def test_disabled_terminal_step_behind_funnel_does_not_raise(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("fun", "funnel"),
            _node("notify", "notify-on-error", disabled=True),
        ]
        edges = [
            _edge("a", "fun", source_handle="failure"),
            _edge("fun", "notify", target_handle="input"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)

        r_nodes, r_edges = self.runner.load_execution_graph(wf)

        self.assertEqual({n["id"] for n in r_nodes}, {"a"})
        self.assertEqual(r_edges, [])

    def test_disabled_step_between_two_funnels_does_not_raise(self) -> None:
        nodes = [
            _node("a", "run-command"),
            _node("fun1", "funnel"),
            _node("x", "run-command", disabled=True),
            _node("fun2", "funnel"),
            _node("sink", "run-command"),
        ]
        edges = [
            _edge("a", "fun1", source_handle="failure"),
            _edge("fun1", "x"),
            _edge("x", "fun2"),
            _edge("fun2", "sink", target_handle="input"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)

        r_nodes, r_edges = self.runner.load_execution_graph(wf)

        self.assertEqual({n["id"] for n in r_nodes}, {"a", "sink"})
        self.assertEqual(len(r_edges), 1)
        self.assertEqual(r_edges[0]["source"], "a")
        self.assertEqual(r_edges[0]["target"], "sink")
        self.assertEqual(r_edges[0]["sourceHandle"], "failure")


class DisabledStepExecutionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.runner = StepRunner(self.db)

    def test_disabled_step_excluded_from_execution_plan(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("skip", "run-command", disabled=True),
            _node("cmd", "run-command"),
        ]
        edges = [_edge("inv", "skip"), _edge("skip", "cmd")]

        plan_ids = [n["id"] for n in self.runner.build_execution_plan(nodes, edges)]

        self.assertEqual(plan_ids, ["inv", "cmd"])


class DisabledStepEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """A disabled mid-chain step behaves exactly as if it were absent: it is
    never invoked, gets no step-result row, and the downstream step runs once
    with the upstream step's context."""

    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.run_repo = RunRepository(self.db)
        self.runner = StepRunner(self.db)

    def _step_results_for(self, run_id: int) -> dict[str, WorkflowStepResult]:
        return {r.step_node_id: r for r in self.run_repo.get_step_results_for_run(run_id)}

    async def test_disabled_step_is_skipped_and_downstream_still_runs(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("disabled", "run-command", disabled=True),
            _node("cmd", "run-command"),
        ]
        edges = [
            _edge("inv", "disabled"),
            _edge("disabled", "cmd", target_handle="input"),
        ]
        wf = SimpleNamespace(id=1, canvas_nodes=nodes, canvas_edges=edges)
        run = _make_run(self.db)
        ctx = AsyncMock()
        called_nodes: list[str] = []
        cmd_devices: dict[str, DeviceContext] = {}

        async def _execute_step_stub(**kwargs: Any) -> list[StepOutcome]:
            node_id = kwargs["node_id"]
            context: WorkflowContext = kwargs["context"]
            called_nodes.append(node_id)
            if node_id == "inv":
                devices = {"d1": _device("d1"), "d2": _device("d2")}
                seeded = context.model_copy(update={"devices": devices})
                return [StepOutcome(name="success", context=seeded)]
            if node_id == "cmd":
                cmd_devices.update(context.devices)
                return [StepOutcome(name="success", context=context)]
            raise AssertionError(f"disabled node {node_id!r} must not execute")

        with patch.object(StepRunner, "_execute_step", side_effect=_execute_step_stub):
            final_status, fan_out, _ = await _run_steps_until_fan_out_or_done(
                run_repo=self.run_repo, runner=self.runner, run=run, wf=wf, ctx=ctx
            )

        self.assertIsNone(fan_out)
        self.assertEqual(final_status, "success")
        self.assertEqual(called_nodes, ["inv", "cmd"])
        self.assertNotIn("disabled", called_nodes)

        results = self._step_results_for(run.id)
        self.assertNotIn("disabled", results)
        self.assertEqual(set(cmd_devices), {"d1", "d2"})


if __name__ == "__main__":
    unittest.main()
