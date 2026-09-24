"""Tests for scripts/ai_layout.py — the auto-layout helper for AI-authored
canvas patches, see doc/ai_workflows/PROCESS.md's "Auto-layout helper" open
item."""

from __future__ import annotations

import unittest
from typing import Any

from scripts.ai_layout import (
    COLUMN_GUTTER,
    NODE_HEIGHT,
    NODE_WIDTH,
    ROW_GUTTER,
    apply_layout,
    compute_layer_layout,
)
from services.execution.graph import GraphCycleError


class _FakePlugin:
    def __init__(self, executable: bool = True) -> None:
        self.executable = executable


class _FakeRegistry:
    """Duck-types the one PluginRegistryService method
    graph_resolution.is_executable_node calls."""

    def __init__(self, executable_by_kind: dict[str, bool]) -> None:
        self._executable_by_kind = executable_by_kind

    def get_plugin(self, plugin_id: str) -> _FakePlugin | None:
        if plugin_id not in self._executable_by_kind:
            return None
        return _FakePlugin(executable=self._executable_by_kind[plugin_id])


def _node(node_id: str, kind: str = "run-command", disabled: bool = False) -> dict[str, Any]:
    return {
        "id": node_id,
        "position": {"x": -1, "y": -1},
        "data": {"kind": kind, "disabled": disabled},
    }


def _edge(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target}


class ComputeLayerLayoutTests(unittest.TestCase):
    def test_linear_chain_gets_one_column_per_node(self) -> None:
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("b", "c")]

        positions = compute_layer_layout(nodes, edges)

        self.assertEqual(positions["a"], {"x": 0, "y": 0})
        self.assertEqual(positions["b"], {"x": NODE_WIDTH + COLUMN_GUTTER, "y": 0})
        self.assertEqual(positions["c"], {"x": 2 * (NODE_WIDTH + COLUMN_GUTTER), "y": 0})

    def test_parallel_branches_share_a_column_stacked_by_row(self) -> None:
        # a -> b, a -> c: b and c are independent siblings, same column.
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("a", "c")]

        positions = compute_layer_layout(nodes, edges)

        self.assertEqual(positions["a"], {"x": 0, "y": 0})
        self.assertEqual(positions["b"]["x"], positions["c"]["x"])
        self.assertNotEqual(positions["b"]["y"], positions["c"]["y"])
        self.assertEqual({positions["b"]["y"], positions["c"]["y"]}, {0, NODE_HEIGHT + ROW_GUTTER})

    def test_join_node_placed_after_its_furthest_parent(self) -> None:
        # a -> c, b -> c, with b -> d also present so b is one column deeper
        # than a: c must land in the column after the FURTHEST parent (b's),
        # not just after a.
        nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
        edges = [_edge("a", "c"), _edge("b", "d"), _edge("d", "c")]

        positions = compute_layer_layout(nodes, edges)

        self.assertGreater(positions["c"]["x"], positions["a"]["x"])
        self.assertGreater(positions["c"]["x"], positions["d"]["x"])

    def test_isolated_nodes_all_land_in_column_zero(self) -> None:
        nodes = [_node("a"), _node("b")]
        positions = compute_layer_layout(nodes, edges=[])

        self.assertEqual(positions["a"]["x"], 0)
        self.assertEqual(positions["b"]["x"], 0)

    def test_cycle_raises_graph_cycle_error(self) -> None:
        nodes = [_node("a"), _node("b")]
        edges = [_edge("a", "b"), _edge("b", "a")]

        with self.assertRaises(GraphCycleError):
            compute_layer_layout(nodes, edges)

    def test_decoration_node_excluded_when_registry_provided(self) -> None:
        nodes = [_node("a", kind="run-command"), _node("label-1", kind="label")]
        edges: list[dict[str, Any]] = []
        registry = _FakeRegistry({"run-command": True, "label": False})

        positions = compute_layer_layout(nodes, edges, registry=registry)

        self.assertIn("a", positions)
        self.assertNotIn("label-1", positions)

    def test_disabled_step_excluded_when_registry_provided(self) -> None:
        nodes = [_node("a"), _node("b", disabled=True)]
        edges = [_edge("a", "b")]
        registry = _FakeRegistry({"run-command": True})

        positions = compute_layer_layout(nodes, edges, registry=registry)

        self.assertIn("a", positions)
        self.assertNotIn("b", positions)

    def test_without_registry_every_node_is_treated_as_executable(self) -> None:
        nodes = [_node("a"), _node("label-1", kind="label")]
        positions = compute_layer_layout(nodes, edges=[])

        self.assertIn("a", positions)
        self.assertIn("label-1", positions)


class ApplyLayoutTests(unittest.TestCase):
    def test_returns_new_nodes_with_position_replaced(self) -> None:
        nodes = [_node("a"), _node("b")]
        edges = [_edge("a", "b")]

        result = apply_layout(nodes, edges)

        self.assertEqual(result[0]["position"], {"x": 0, "y": 0})
        self.assertEqual(result[1]["position"], {"x": NODE_WIDTH + COLUMN_GUTTER, "y": 0})
        # Original list/nodes are untouched (no in-place mutation).
        self.assertEqual(nodes[0]["position"], {"x": -1, "y": -1})

    def test_decoration_node_position_left_untouched(self) -> None:
        nodes = [_node("a"), _node("label-1", kind="label")]
        registry = _FakeRegistry({"run-command": True, "label": False})

        result = apply_layout(nodes, edges=[], registry=registry)

        by_id = {n["id"]: n for n in result}
        self.assertEqual(by_id["label-1"]["position"], {"x": -1, "y": -1})
        self.assertEqual(by_id["a"]["position"], {"x": 0, "y": 0})

    def test_node_missing_id_is_passed_through_unchanged(self) -> None:
        nodes = [_node("a"), {"data": {"kind": "run-command"}, "position": {"x": 5, "y": 5}}]

        result = apply_layout(nodes, edges=[])

        self.assertEqual(result[1], {"data": {"kind": "run-command"}, "position": {"x": 5, "y": 5}})


if __name__ == "__main__":
    unittest.main()
