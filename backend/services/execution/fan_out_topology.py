"""Save-time / pre-run check of the fan-out topology rules R1-R3 (DN-D).

With ``R = downstream(inventory)`` and ``d(x)`` the topological depth:

* R1 every executable node outside ``R + {inventory}`` has ``d(x) <= d(inventory)``
  (it runs in phase 1, before the fan-out);
* R2 every in-edge of a node in ``R`` comes from ``R + {inventory}`` (children and the
  post-join walk receive nothing else);
* R3 at most one fan-out step is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.execution.graph import (
    downstream_node_ids,
    topological_generations,
    topological_order,
)
from services.execution.step_runner import graph_resolution as gr

# Mirrors the `executable: false` entries of registry.yaml (label, background, funnel, step-group);
# tests/unit/test_fan_out_topology.py::test_canvas_only_kinds_match_registry keeps them in step.
CANVAS_ONLY_KINDS = frozenset({"label", "background", "funnel", "step-group"})


@dataclass(frozen=True)
class FanOutViolation:
    rule: str  # "R1" | "R2" | "R3"
    node_id: str
    message: str


def _enabled_fan_out_ids(nodes: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for node in nodes:
        config = (node.get("data") or {}).get("pluginConfig") or {}
        fan_out = config.get("fan_out") or {}
        if "id" in node and isinstance(fan_out, dict) and fan_out.get("enabled"):
            ids.append(node["id"])
    return ids


def validate_fan_out_topology(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[FanOutViolation]:
    """Violations on the graph the engine really walks (funnels, disabled steps and stop-here
    resolved, canvas decorations dropped). Empty list: fine, or not applicable."""
    try:
        nodes, edges = gr.resolve_funnels(nodes, edges)
        nodes, edges = gr.resolve_disabled_steps(nodes, edges)
        nodes, edges = gr.resolve_stop_here(nodes, edges)
        executable = [
            n for n in nodes if (n.get("data") or {}).get("kind") not in CANVAS_ONLY_KINDS
        ]
        ids = {n["id"] for n in executable if "id" in n}
        edges = [e for e in edges if e.get("source") in ids and e.get("target") in ids]
        ordered = topological_order(executable, edges)
    except ValueError:
        return []  # malformed funnel / cycle: the other validators report those
    fan_out = _enabled_fan_out_ids(executable)
    if not fan_out:
        return []

    depth = {
        n["id"]: d for d, wave in enumerate(topological_generations(ordered, edges)) for n in wave
    }
    violations: list[FanOutViolation] = []
    inventory = min(fan_out, key=lambda node_id: depth[node_id])
    for extra in fan_out:  # R3
        if extra != inventory:
            violations.append(
                FanOutViolation(
                    "R3",
                    extra,
                    f"Only one step may have fan-out enabled (also enabled on {inventory!r}).",
                )
            )
    region = downstream_node_ids(inventory, executable, edges)
    for node_id in sorted(ids - region - {inventory}):  # R1
        if depth[node_id] > depth[inventory]:
            violations.append(
                FanOutViolation(
                    "R1",
                    node_id,
                    f"Step {node_id!r} is not connected to the fan-out step {inventory!r} but "
                    "would only run after it, so it would never execute. Connect it below the "
                    "fan-out step, move it before it, or turn fan-out off.",
                )
            )
    for edge in edges:  # R2
        source, target = edge.get("source"), edge.get("target")
        if target in region and source not in region and source != inventory:
            violations.append(
                FanOutViolation(
                    "R2",
                    target,
                    f"Step {target!r} below the fan-out step {inventory!r} also receives input "
                    f"from {source!r}, which is outside the fan-out branch; branches only "
                    "receive the fan-out step's devices. Connect it through the fan-out step "
                    "or remove the edge.",
                )
            )
    return violations
