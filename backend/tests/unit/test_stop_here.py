"""Tests for the stop-here node: graph truncation and the pass-through executor."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.execution.step_runner.graph_resolution import resolve_stop_here
from workflow_steps.stop_here.executor import execute as stop_here_execute


def _node(node_id: str, kind: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target}


# inv -> a -> stop -> b -> c
_NODES = [
    _node("inv", "get-nautobot-devices"),
    _node("a", "get-device-configs"),
    _node("stop", "stop-here"),
    _node("b", "run-command"),
    _node("c", "store-artifact"),
]
_EDGES = [
    _edge("inv", "a"),
    _edge("a", "stop"),
    _edge("stop", "b"),
    _edge("b", "c"),
]


class ResolveStopHereTests(unittest.TestCase):
    def test_no_stop_here_node_is_a_no_op(self) -> None:
        nodes = [n for n in _NODES if n["id"] != "stop"]
        edges = [e for e in _EDGES if e["source"] != "stop" and e["target"] != "stop"]
        resolved_nodes, resolved_edges = resolve_stop_here(nodes, edges)
        self.assertEqual(resolved_nodes, nodes)
        self.assertEqual(resolved_edges, edges)

    def test_drops_downstream_nodes_and_edges_but_keeps_stop_here(self) -> None:
        resolved_nodes, resolved_edges = resolve_stop_here(_NODES, _EDGES)
        self.assertEqual({n["id"] for n in resolved_nodes}, {"inv", "a", "stop"})
        self.assertEqual(
            {(e["source"], e["target"]) for e in resolved_edges},
            {("inv", "a"), ("a", "stop")},
        )

    def test_chained_stop_here_only_the_first_survives(self) -> None:
        nodes = [*_NODES, _node("stop2", "stop-here")]
        edges = [*_EDGES, _edge("b", "stop2")]
        resolved_nodes, _resolved_edges = resolve_stop_here(nodes, edges)
        self.assertEqual({n["id"] for n in resolved_nodes}, {"inv", "a", "stop"})


class StopHereExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_context_through_and_emits_single_success(self) -> None:
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": device},
            metadata={"upstream.note": "keep"},
        )
        run = MagicMock()
        run.id = 1

        outcomes = await stop_here_execute(
            config={},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="stop",
            device_sessions=MagicMock(),
        )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.name, "success")
        self.assertIs(outcome.context, context)


if __name__ == "__main__":
    unittest.main()
