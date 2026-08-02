"""Pure graph utilities shared by StepRunner (execution) and WorkflowService
(definition validation) — topological ordering and downstream-reachability
over the canvas node/edge shape (``{"id": ...}`` nodes, ``{"source", "target"}``
edges).

Extracted from ``services/execution/step_runner.py`` so cycle detection has a
single implementation instead of being duplicated at both call sites — see
doc/FABLE-ANALYSIS.md §4.2 and §5.3.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class GraphCycleError(ValueError):
    """Raised when canvas nodes/edges contain a cycle.

    Subclasses ValueError so both a workflow-step executor (which must raise
    ValueError for configuration problems) and a FastAPI service (which
    translates ValueError-family exceptions to 400s at the router) can handle
    it without a bespoke except clause.
    """


def topological_order(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return *nodes* in dependency order via Kahn's algorithm.

    Raises ``GraphCycleError`` if any node is unreachable by the sort — i.e.
    it (or an ancestor) sits in a cycle. Callers that need canvas-decoration
    filtering (e.g. StepRunner, which excludes non-executable nodes first)
    must do that before calling this function; it treats every entry in
    *nodes* as a node to order.
    """
    node_map = {n["id"]: n for n in nodes if "id" in n}
    in_degree: dict[str, int] = dict.fromkeys(node_map, 0)
    dependents: dict[str, list[str]] = {nid: [] for nid in node_map}

    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in in_degree and tgt in in_degree:
            in_degree[tgt] += 1
            dependents[src].append(tgt)

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    result: list[dict[str, Any]] = []

    while queue:
        nid = queue.popleft()
        result.append(node_map[nid])
        for dep in dependents[nid]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    if len(result) != len(node_map):
        cyclic_ids = sorted(set(node_map) - {n["id"] for n in result})
        raise GraphCycleError(
            f"Workflow graph contains a cycle involving node(s): {', '.join(cyclic_ids)}"
        )

    return result


def downstream_node_ids(
    start_node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    """Return all node IDs reachable downstream of start_node_id (excluding it)."""
    adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes if "id" in n}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in adjacency and tgt in adjacency:
            adjacency[src].append(tgt)

    visited: set[str] = set()
    queue: deque[str] = deque(adjacency.get(start_node_id, []))
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        queue.extend(adjacency.get(nid, []))
    return visited


def find_join_node_id(
    inventory_node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str | None:
    """Return the first fan-in node downstream of the inventory step, if any.

    v1 supports at most one fan-in node per fanned-out branch; the match is
    deterministic by node list order.
    """
    downstream = downstream_node_ids(inventory_node_id, nodes, edges)
    for node in nodes:
        node_id = node.get("id", "")
        if node_id in downstream and (node.get("data", {}) or {}).get("kind") == "fan-in":
            return node_id
    return None


def child_node_ids(
    inventory_node_id: str,
    join_node_id: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> set[str]:
    """Nodes a fan-out child should execute.

    That is everything downstream of the inventory step, minus the fan-in
    node and everything downstream of it (which the parent runs once after
    the children rejoin). When no fan-in node exists, children run the whole
    downstream subgraph (legacy behaviour).
    """
    downstream = downstream_node_ids(inventory_node_id, nodes, edges)
    if join_node_id is None:
        return downstream
    post_join = {join_node_id} | downstream_node_ids(join_node_id, nodes, edges)
    return downstream - post_join
