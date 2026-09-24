#!/usr/bin/env python3
"""Auto-layout helper for AI-authored canvas patches — computes node
positions from the dependency graph instead of the hand-picked {x, y} values
used so far (see doc/ai_workflows/PROCESS.md's "Auto-layout helper" open
item). Deliberately backend-only: this is for whoever is about to build a
canvas_nodes patch (the AI collaborator, or a human) to call before writing
positions into the patch — it is not wired into ai_workflow_apply.py, which
never lays out nodes itself (see that script's docstring). A user-facing
"Auto Layout" canvas button is a separate, not-yet-built feature (it would
need its own JS implementation — dagre or similar — since React Flow runs
client-side; deliberately out of scope here).

Layout is a simple layered grid, not force-directed:
- Columns = dependency "waves" from services/execution/graph.py::
  topological_generations (the same grouping StepRunner uses to decide what
  may run concurrently) — a node's column is one past the furthest of its
  upstream parents, so every edge points strictly rightward.
- Rows = stacked top-to-bottom within a column, in existing node order.
- Pitch matches the fixed node size from doc/WORKFLOW-STEPS-STYLE_GUIDE.md
  (measured: 320x128) plus a gutter.

This is good enough for an AI-authored draft a human can still drag nodes
around in afterward — not a polished auto-arrange for a hand-built canvas
with many crossing edges.

Canvas decorations (label/background nodes, author-disabled steps) are never
assigned a position here — reuses
services/execution/step_runner/graph_resolution.py's is_executable_node/
filter_executable_graph (the same check StepRunner itself uses) rather than
re-implementing "what counts as a decoration". Pass a PluginRegistryService
to get that filtering; omit it (None) to treat every node in *nodes* as
executable, e.g. when the caller has already filtered decorations out itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from services.execution.graph import topological_generations, topological_order  # noqa: E402
from services.execution.step_runner.graph_resolution import (  # noqa: E402
    filter_executable_graph,
)
from services.plugin_registry.plugin_registry_service import PluginRegistryService  # noqa: E402

# Fixed node size (doc/WORKFLOW-STEPS-STYLE_GUIDE.md: w-80 x h-32 = 320x128)
# plus a gutter roughly matching contributing-data/workflow-gallery examples.
NODE_WIDTH = 320
NODE_HEIGHT = 128
COLUMN_GUTTER = 80
ROW_GUTTER = 40


def compute_layer_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    registry: PluginRegistryService | None = None,
) -> dict[str, dict[str, int]]:
    """Return {node_id: {"x": int, "y": int}} for every executable node in
    *nodes*. Decoration nodes and author-disabled steps are omitted from the
    result — callers should leave those nodes' existing position untouched.
    Raises GraphCycleError (from topological_order) if the executable
    subgraph contains a cycle."""
    if registry is not None:
        executable_nodes, executable_edges = filter_executable_graph(nodes, edges, registry)
    else:
        executable_nodes, executable_edges = nodes, edges

    ordered = topological_order(executable_nodes, executable_edges)
    generations = topological_generations(ordered, executable_edges)

    positions: dict[str, dict[str, int]] = {}
    for column, layer in enumerate(generations):
        for row, node in enumerate(layer):
            positions[node["id"]] = {
                "x": column * (NODE_WIDTH + COLUMN_GUTTER),
                "y": row * (NODE_HEIGHT + ROW_GUTTER),
            }
    return positions


def apply_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    registry: PluginRegistryService | None = None,
) -> list[dict[str, Any]]:
    """Return a NEW node list with every executable node's "position" field
    replaced by compute_layer_layout's result. Decoration/disabled nodes
    (and any node missing an "id") are returned unchanged, same object."""
    positions = compute_layer_layout(nodes, edges, registry)
    return [
        {**node, "position": positions[node["id"]]} if node.get("id") in positions else node
        for node in nodes
    ]
