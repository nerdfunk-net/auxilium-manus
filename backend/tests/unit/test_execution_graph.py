"""Tests for services.execution.graph — extracted from step_runner.py.
See doc/FABLE-ANALYSIS.md §4.2, §5.3."""

from __future__ import annotations

import pytest

from services.execution.graph import (
    GraphCycleError,
    child_node_ids,
    downstream_node_ids,
    find_join_node_id,
    topological_generations,
    topological_order,
)


def _node(node_id: str, kind: str = "log-message") -> dict:
    return {"id": node_id, "data": {"kind": kind}}


def _edge(source: str, target: str) -> dict:
    return {"source": source, "target": target}


class TestTopologicalOrder:
    def test_linear_chain_orders_by_dependency(self) -> None:
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("b", "c")]

        ordered = topological_order(nodes, edges)

        assert [n["id"] for n in ordered] == ["a", "b", "c"]

    def test_disconnected_nodes_all_included(self) -> None:
        nodes = [_node("a"), _node("b")]
        ordered = topological_order(nodes, edges=[])
        assert {n["id"] for n in ordered} == {"a", "b"}

    def test_direct_cycle_raises(self) -> None:
        nodes = [_node("a"), _node("b")]
        edges = [_edge("a", "b"), _edge("b", "a")]

        with pytest.raises(GraphCycleError, match="a|b"):
            topological_order(nodes, edges)

    def test_self_loop_raises(self) -> None:
        nodes = [_node("a")]
        edges = [_edge("a", "a")]

        with pytest.raises(GraphCycleError):
            topological_order(nodes, edges)

    def test_cycle_downstream_of_valid_prefix_raises(self) -> None:
        # a -> b -> c -> b (cycle does not include the entry node "a")
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("b", "c"), _edge("c", "b")]

        with pytest.raises(GraphCycleError):
            topological_order(nodes, edges)


class TestTopologicalGenerations:
    def test_linear_chain_one_node_per_generation(self) -> None:
        nodes = [_node("a"), _node("b"), _node("c")]
        edges = [_edge("a", "b"), _edge("b", "c")]

        generations = topological_generations(topological_order(nodes, edges), edges)

        assert [[n["id"] for n in gen] for gen in generations] == [["a"], ["b"], ["c"]]

    def test_diamond_groups_independent_siblings_together(self) -> None:
        nodes = [_node("a"), _node("b1"), _node("b2"), _node("c")]
        edges = [
            _edge("a", "b1"),
            _edge("a", "b2"),
            _edge("b1", "c"),
            _edge("b2", "c"),
        ]

        generations = topological_generations(topological_order(nodes, edges), edges)

        assert [{n["id"] for n in gen} for gen in generations] == [
            {"a"},
            {"b1", "b2"},
            {"c"},
        ]

    def test_disconnected_nodes_share_a_generation(self) -> None:
        nodes = [_node("a"), _node("b")]

        generations = topological_generations(topological_order(nodes, edges=[]), edges=[])

        assert len(generations) == 1
        assert {n["id"] for n in generations[0]} == {"a", "b"}

    def test_three_way_fan_in_is_one_generation(self) -> None:
        # configs -> {parse_cisco, batfish, pyats} -> fan_in
        nodes = [
            _node("configs"),
            _node("parse_cisco"),
            _node("batfish"),
            _node("pyats"),
            _node("fan_in", "fan-in"),
        ]
        edges = [
            _edge("configs", "parse_cisco"),
            _edge("configs", "batfish"),
            _edge("configs", "pyats"),
            _edge("parse_cisco", "fan_in"),
            _edge("batfish", "fan_in"),
            _edge("pyats", "fan_in"),
        ]

        generations = topological_generations(topological_order(nodes, edges), edges)

        assert [{n["id"] for n in gen} for gen in generations] == [
            {"configs"},
            {"parse_cisco", "batfish", "pyats"},
            {"fan_in"},
        ]


class TestDownstreamNodeIds:
    def test_returns_transitive_downstream_only(self) -> None:
        nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
        edges = [_edge("a", "b"), _edge("b", "c"), _edge("a", "d")]

        assert downstream_node_ids("a", nodes, edges) == {"b", "c", "d"}
        assert downstream_node_ids("c", nodes, edges) == set()


class TestFindJoinNodeId:
    def test_finds_fan_in_downstream(self) -> None:
        nodes = [_node("inv", "get-nautobot-devices"), _node("fi", "fan-in")]
        edges = [_edge("inv", "fi")]

        assert find_join_node_id("inv", nodes, edges) == "fi"

    def test_returns_none_when_no_fan_in(self) -> None:
        nodes = [_node("inv"), _node("x")]
        edges = [_edge("inv", "x")]

        assert find_join_node_id("inv", nodes, edges) is None


class TestChildNodeIds:
    def test_excludes_join_and_post_join_nodes(self) -> None:
        nodes = [_node("inv"), _node("x"), _node("fi", "fan-in"), _node("y")]
        edges = [_edge("inv", "x"), _edge("x", "fi"), _edge("fi", "y")]

        assert child_node_ids("inv", "fi", nodes, edges) == {"x"}

    def test_legacy_behaviour_without_join_node(self) -> None:
        nodes = [_node("inv"), _node("x"), _node("y")]
        edges = [_edge("inv", "x"), _edge("x", "y")]

        assert child_node_ids("inv", None, nodes, edges) == {"x", "y"}
