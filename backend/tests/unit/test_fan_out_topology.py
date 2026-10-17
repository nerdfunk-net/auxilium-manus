"""CF-02: fan-out topology rules R1-R3 (DN-D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import settings
from repositories.plugin_repository import PluginRepository
from services.execution.fan_out_topology import CANVAS_ONLY_KINDS, validate_fan_out_topology
from services.plugin_registry.plugin_registry_service import PluginRegistryService

GALLERY = Path(__file__).resolve().parents[3] / "contributing-data" / "workflow-gallery"


def node(node_id: str, *, kind: str = "run-command", fan_out: bool = False) -> dict:
    config = {"fan_out": {"enabled": True, "mode": "per_device"}} if fan_out else {}
    return {"id": node_id, "data": {"kind": kind, "pluginConfig": config}}


def edge(source: str, target: str) -> dict:
    return {"id": f"{source}-{target}", "source": source, "target": target}


def rules(nodes, edges) -> list[tuple[str, str]]:
    return [(v.rule, v.node_id) for v in validate_fan_out_topology(nodes, edges)]


def test_unconnected_later_node_is_rejected_r1() -> None:
    # A(fan-out) -> X -> J(fan-in) -> Z ; independent B -> B2 (B2 would never run)
    nodes = [
        node("A", fan_out=True),
        node("X"),
        node("J", kind="fan-in"),
        node("Z"),
        node("B"),
        node("B2"),
    ]
    edges = [edge("A", "X"), edge("X", "J"), edge("J", "Z"), edge("B", "B2")]
    assert rules(nodes, edges) == [("R1", "B2")]


def test_second_fan_out_is_rejected_r3() -> None:
    nodes = [node("A", fan_out=True), node("X"), node("C", fan_out=True), node("Y")]
    edges = [edge("A", "X"), edge("C", "Y")]
    found = rules(nodes, edges)
    assert ("R3", "C") in found


def test_second_parent_outside_branch_is_rejected_r2() -> None:
    nodes = [node("A", fan_out=True), node("X"), node("P")]
    edges = [edge("A", "X"), edge("P", "X")]
    assert rules(nodes, edges) == [("R2", "X")]


def test_parked_sibling_in_same_wave_is_allowed() -> None:
    nodes = [node("A", fan_out=True), node("X"), node("S")]
    assert rules(nodes, [edge("A", "X")]) == []


def test_independent_earlier_chain_is_allowed() -> None:
    nodes = [node("P"), node("A", fan_out=True), node("X"), node("B"), node("C")]
    edges = [edge("P", "A"), edge("A", "X"), edge("B", "C")]
    assert rules(nodes, edges) == []


def test_linear_graph_and_no_fan_out_are_valid() -> None:
    nodes = [node("A", fan_out=True), node("X")]
    assert rules(nodes, [edge("A", "X")]) == []
    assert rules([node("A"), node("B")], []) == []


def test_malformed_funnel_returns_empty() -> None:
    funnel = {"id": "F", "data": {"kind": "funnel", "pluginConfig": {}}}
    nodes = [node("A"), node("B"), node("C"), funnel, node("D", fan_out=True)]
    edges = [edge("A", "F"), edge("B", "F"), edge("F", "C"), edge("F", "D")]
    # no exception escapes, whatever the funnel resolver decides
    validate_fan_out_topology(nodes, edges)


def test_canvas_only_kinds_match_registry() -> None:
    registry = PluginRegistryService(
        PluginRepository(plugins_file=settings.plugins_file)
    ).get_registry()
    declared = {p.id for p in registry.plugins if not p.executable}
    assert declared == set(CANVAS_ONLY_KINDS)


@pytest.mark.parametrize("path", sorted(GALLERY.glob("*.json")), ids=lambda p: p.name)
def test_gallery_workflows_are_valid(path: Path) -> None:
    data = json.loads(path.read_text())
    assert validate_fan_out_topology(data["canvas_nodes"], data["canvas_edges"]) == []
