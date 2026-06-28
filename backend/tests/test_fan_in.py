"""Tests for the fan-in node: boundary helpers and the pass-through executor."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.execution.step_runner import StepRunner
from workflow_steps.fan_in.executor import execute as fan_in_execute


def _node(node_id: str, kind: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target}


# Diamond graph:  inv -> a -> join -> store
#                 inv -> b -> join
_NODES = [
    _node("inv", "get-nautobot-devices"),
    _node("a", "get-device-configs"),
    _node("b", "run-command"),
    _node("join", "fan-in"),
    _node("store", "store-artifact"),
]
_EDGES = [
    _edge("inv", "a"),
    _edge("inv", "b"),
    _edge("a", "join"),
    _edge("b", "join"),
    _edge("join", "store"),
]


class FanInBoundaryHelperTests(unittest.TestCase):
    def test_find_join_node_id_returns_fan_in_node(self) -> None:
        self.assertEqual(
            StepRunner._find_join_node_id("inv", _NODES, _EDGES),
            "join",
        )

    def test_find_join_node_id_none_when_absent(self) -> None:
        nodes = [n for n in _NODES if n["id"] != "join"]
        edges = [
            _edge("inv", "a"),
            _edge("inv", "b"),
            _edge("a", "store"),
        ]
        self.assertIsNone(StepRunner._find_join_node_id("inv", nodes, edges))

    def test_child_node_ids_excludes_join_and_descendants(self) -> None:
        self.assertEqual(
            StepRunner._child_node_ids("inv", "join", _NODES, _EDGES),
            {"a", "b"},
        )

    def test_child_node_ids_equals_full_downstream_without_join(self) -> None:
        self.assertEqual(
            StepRunner._child_node_ids("inv", None, _NODES, _EDGES),
            {"a", "b", "join", "store"},
        )

    def test_downstream_of_join_is_post_join_set(self) -> None:
        self.assertEqual(
            StepRunner._downstream_node_ids("join", _NODES, _EDGES),
            {"store"},
        )


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
        status=DeviceStatus.OK,
    )


class FanInExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_context_through_and_emits_single_success(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1"), "d2": _device("d2")},
            metadata={"upstream.note": "keep"},
        )
        run = MagicMock()
        run.id = 1

        outcomes = await fan_in_execute(
            config={},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="join",
        )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.name, "success")
        # Devices and their capabilities pass through unchanged.
        self.assertEqual(set(outcome.context.devices), {"d1", "d2"})
        self.assertIn(
            Capability.RUNNING_CONFIG, outcome.context.devices["d1"].capabilities
        )
        # Upstream metadata preserved; device_count stamped.
        self.assertEqual(outcome.context.metadata["upstream.note"], "keep")
        self.assertEqual(outcome.context.metadata["join.fan_in"], {"device_count": 2})

    async def test_empty_context_still_emits_success(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        run = MagicMock()
        run.id = 1

        outcomes = await fan_in_execute(
            config={},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="join",
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(
            outcomes[0].context.metadata["join.fan_in"], {"device_count": 0}
        )


if __name__ == "__main__":
    unittest.main()
