"""Pure canvas-graph resolution: splice out funnel nodes and author-disabled
steps, drop non-executable decorations, and produce the executable-filtered
topological order. No DB, no StepRunner state — the plugin registry is passed
in explicitly.

Extracted from step_runner so the "what graph do we actually walk" logic has
one home and can be unit-tested in isolation (it already is — see
test_step_runner_funnel.py / test_step_runner_disabled_steps.py). StepRunner
keeps thin delegating wrappers so ``StepRunner._resolve_funnels`` etc. still
resolve for external and test callers.
"""

from __future__ import annotations

from typing import Any

from services.execution.graph import topological_order
from services.plugin_registry.plugin_registry_service import PluginRegistryService

# Graph-structure node kinds that never honour an author "disabled" flag —
# splicing them out would silently reshape fan-out join / merge behaviour.
_STRUCTURAL_KINDS = frozenset({"fan-in"})


def _is_author_disabled(node: dict[str, Any]) -> bool:
    """True when the author toggled this step off *and* it is a real step
    (not a structural node like ``fan-in``)."""
    data = node.get("data") or {}
    return data.get("disabled") is True and data.get("kind") not in _STRUCTURAL_KINDS


def resolve_disabled_steps(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splice every step flagged ``data.disabled: true`` out of the graph.

    Two shapes, one rule:

    * **Parked** — a disabled step with no connections is simply dropped.
    * **Bypassed** — a disabled step wired between neighbours is removed and
      each edge coming into it is rewired straight to whatever *enabled*
      node(s) lie beyond it. The walk passes through consecutive disabled
      steps, so a whole chain ``A -> X(off) -> Y(off) -> B`` collapses to
      ``A -> B``. The upstream edge keeps its ``sourceHandle`` (outcome
      name); the far edge's ``targetHandle`` is carried over — same
      contract as ``resolve_funnels``.

    When a disabled step *branches* (more than one outgoing edge), only its
    ``success``/default outcome passes through — a ``failure``/error branch
    must never fire on an otherwise-successful run. A lone outgoing edge is
    unambiguous and is always followed.

    Graph-structure nodes (``fan-in``) ignore the flag entirely: removing a
    join point would silently change fan-out merge semantics. Disabled
    steps that form a cycle among themselves are skipped rather than
    recursed into. Runs *after* ``resolve_funnels`` so a dropped or
    rewired edge can never leave a funnel malformed.
    """
    disabled_ids = {
        n["id"] for n in nodes if "id" in n and _is_author_disabled(n)
    }
    if not disabled_ids:
        return nodes, edges

    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        outgoing.setdefault(edge.get("source", ""), []).append(edge)

    def enabled_targets_beyond(
        disabled_id: str, seen: set[str]
    ) -> list[tuple[str, Any]]:
        out_edges = outgoing.get(disabled_id, [])
        if len(out_edges) > 1:
            out_edges = [
                e
                for e in out_edges
                if (e.get("sourceHandle") or "success") == "success"
            ]
        reached: list[tuple[str, Any]] = []
        for edge in out_edges:
            target = edge.get("target", "")
            if not target:
                continue
            if target in disabled_ids:
                if target not in seen:
                    reached.extend(enabled_targets_beyond(target, seen | {target}))
            else:
                reached.append((target, edge.get("targetHandle")))
        return reached

    resolved_edges: list[dict[str, Any]] = []
    seen_wires: set[tuple[str, Any, str, Any]] = set()

    def keep(edge: dict[str, Any]) -> None:
        wire = (
            edge.get("source", ""),
            edge.get("sourceHandle"),
            edge.get("target", ""),
            edge.get("targetHandle"),
        )
        if wire in seen_wires:
            return
        seen_wires.add(wire)
        resolved_edges.append(edge)

    for edge in edges:
        if edge.get("source", "") in disabled_ids:
            continue  # replaced by the rewiring below, or dropped
        target = edge.get("target", "")
        if target not in disabled_ids:
            keep(edge)
            continue
        for far_target, far_handle in enabled_targets_beyond(target, {target}):
            keep(
                {
                    **edge,
                    "id": f"{edge.get('id', 'edge')}::bypass::{far_target}",
                    "target": far_target,
                    "targetHandle": far_handle,
                }
            )

    remaining_nodes = [n for n in nodes if n.get("id") not in disabled_ids]
    return remaining_nodes, resolved_edges


def resolve_funnels(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splice funnel nodes out of the graph: every edge into a funnel is
    rewired straight to the funnel's one downstream target, keeping the
    original edge's sourceHandle (outcome name) so e.g. a ``failure``
    edge funneled into Notify On Error still reads as a failure edge.
    Funnel nodes themselves are dropped, same as any other
    ``executable: false`` decoration.
    """
    funnel_ids = {
        n["id"] for n in nodes if "id" in n and (n.get("data") or {}).get("kind") == "funnel"
    }
    if not funnel_ids:
        return nodes, edges

    outgoing_by_funnel: dict[str, dict[str, Any]] = {}
    for funnel_id in funnel_ids:
        outgoing = [e for e in edges if e.get("source") == funnel_id]
        if len(outgoing) != 1:
            raise ValueError(
                f"Funnel node {funnel_id!r} must have exactly one outgoing "
                f"connection (found {len(outgoing)})"
            )
        downstream_target = outgoing[0].get("target", "")
        if downstream_target in funnel_ids:
            raise ValueError(
                f"Funnel node {funnel_id!r} feeds into another funnel "
                f"{downstream_target!r} — chaining funnels is not supported"
            )
        outgoing_by_funnel[funnel_id] = outgoing[0]

    resolved_edges = [
        e
        for e in edges
        if e.get("source") not in funnel_ids and e.get("target") not in funnel_ids
    ]
    for edge in edges:
        target = edge.get("target", "")
        if target not in funnel_ids:
            continue
        downstream_edge = outgoing_by_funnel[target]
        resolved_edges.append(
            {
                **edge,
                "target": downstream_edge.get("target", ""),
                "targetHandle": downstream_edge.get("targetHandle"),
            }
        )

    remaining_nodes = [n for n in nodes if n.get("id") not in funnel_ids]
    return remaining_nodes, resolved_edges


def is_executable_node(node: dict[str, Any], registry: PluginRegistryService) -> bool:
    """False for canvas decorations (label, background, …) and steps the
    author has disabled; True otherwise.

    Disabled steps are normally already spliced out by
    ``resolve_disabled_steps`` in ``StepRunner.load_execution_graph``; this is a
    belt-and-braces check for any caller that reaches the topological sort
    with a raw graph (it yields "parked" semantics — the node and its
    edges are dropped rather than bypassed).

    Unknown kinds stay executable so StepRunner still fails with
    ``Unknown step type`` rather than silently dropping them.
    """
    if _is_author_disabled(node):
        return False
    data = node.get("data") or {}
    kind = data.get("kind", "")
    if not kind:
        return True
    plugin = registry.get_plugin(kind)
    if plugin is None:
        return True
    return plugin.executable


def filter_executable_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    registry: PluginRegistryService,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop non-executable decoration nodes and any edges that touch them."""
    executable_nodes = [n for n in nodes if is_executable_node(n, registry)]
    executable_ids = {n["id"] for n in executable_nodes if "id" in n}
    executable_edges = [
        e
        for e in edges
        if e.get("source", "") in executable_ids and e.get("target", "") in executable_ids
    ]
    return executable_nodes, executable_edges


def topological_sort(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    registry: PluginRegistryService,
) -> list[dict[str, Any]]:
    """Executable-node-filtered topological order.

    Raises ``GraphCycleError`` (a ``ValueError``) if the graph contains a
    cycle — see ``services.execution.graph.topological_order``. Workflow
    definitions are also validated for cycles at save time
    (``WorkflowService``), but this is defense in depth: canvas data can
    change between save and run (e.g. direct DB edits, older saved
    workflows from before that validation existed).
    """
    executable_nodes, executable_edges = filter_executable_graph(nodes, edges, registry)
    return topological_order(executable_nodes, executable_edges)
