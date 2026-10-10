"""Compact workflow plan <-> persisted canvas (doc/ai_integration/AI_ASSISTANT.md §9c).

A persisted canvas node carries ~20 fields (denormalized registry data, ``measured``, ``stepUuid``,
positions...) and edges follow a fixed id/handle scheme. Models work in a compact vocabulary
(``{id, kind, title, config}`` nodes, ``{from, outcome, to}`` edges); this module expands a plan
into the persisted shape *merged onto the canvas the user has open*, so untouched nodes keep their
position, size and identity, and decorations/groups pass through.

Pure functions only: no database, no I/O. Reference checks and the capability/attribute tiers are
the job of ``WorkflowValidationService``, run on the result by the propose tool.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.plugins import PluginDefinition
from models.workflows import StaticAttributeDef
from services.ai_assistant.redaction import Redactor
from services.workflow_context.secret_fields import redact_secrets_in_data

STEP_NODE_TYPE = "workflowNode"
FUNNEL_KIND = "funnel"
NODE_WIDTH = 320
NODE_HEIGHT = 128
PITCH_X = NODE_WIDTH + 80
PITCH_Y = NODE_HEIGHT + 40
MAX_PLAN_NODES = 300
MAX_PLAN_EDGES = 600
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


class PluginLookup(Protocol):
    def get_plugin(
        self, plugin_id: str, include_disabled: bool = False
    ) -> PluginDefinition | None: ...


class PlanError(Exception):
    """The plan cannot be expanded; every message is addressed to the model so it can fix it."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


class PlanNodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        pattern=_ID_PATTERN, description="Unique id; keep the existing id for a step you keep"
    )
    kind: str = Field(min_length=1, max_length=100, description="Registry step id")
    title: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict, description="The step's pluginConfig")
    disabled: bool = False


class PlanEdgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(alias="from", pattern=_ID_PATTERN)
    outcome: str = Field(default="success", max_length=64)
    target: str = Field(alias="to", pattern=_ID_PATTERN)


class WorkflowPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[PlanNodeIn] = Field(max_length=MAX_PLAN_NODES)
    edges: list[PlanEdgeIn] = Field(default_factory=list, max_length=MAX_PLAN_EDGES)
    static_attributes: list[dict[str, Any]] | None = Field(
        default=None,
        description="Full replacement of the workflow's static attributes; omit to leave unchanged",
    )


@dataclass(frozen=True)
class ExpandedWorkflow:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    static_attributes: list[dict[str, Any]]
    changes: dict[str, Any]


# -- helpers --------------------------------------------------------------------------------


def _data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _kind(node: dict[str, Any]) -> str | None:
    data = node.get("data")
    kind = data.get("kind") if isinstance(data, dict) else None
    return kind if isinstance(kind, str) else None


def is_plan_managed(node: dict[str, Any]) -> bool:
    """Executable steps and funnels are part of the plan; labels, backgrounds etc. are not."""
    return node.get("type") == STEP_NODE_TYPE or _kind(node) == FUNNEL_KIND


def _edge_key(source: str, handle: str, target: str) -> tuple[str, str, str]:
    return (source, handle, target)


def _edge_id(source: str, outcome: str, target: str) -> str:
    return f"xy-edge__{source}{outcome}-{target}input"


def _config_text(config: Any) -> str:
    return json.dumps(config, indent=2, sort_keys=True, default=str)


def _topological_order(ids: list[str], edges: list[tuple[str, str]]) -> list[str] | None:
    indegree = {node_id: 0 for node_id in ids}
    children: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for source, target in edges:
        children[source].append(target)
        indegree[target] += 1
    queue = deque(node_id for node_id in ids if indegree[node_id] == 0)
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    return order if len(order) == len(ids) else None


# -- compact view (canvas -> model) ----------------------------------------------------------


def build_compact_view(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    static_attributes: list[dict[str, Any]],
    redactor: Redactor,
) -> dict[str, Any]:
    managed_ids = {n["id"] for n in nodes if is_plan_managed(n) and "id" in n}
    compact_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("id") not in managed_ids:
            continue
        data = _data(node)
        entry: dict[str, Any] = {"id": node["id"], "kind": data.get("kind")}
        if entry["kind"] != FUNNEL_KIND:
            entry["title"] = data.get("title")
            entry["config"] = redactor.tokenize_data(data.get("pluginConfig") or {})
            if data.get("disabled"):
                entry["disabled"] = True
        compact_nodes.append(entry)
    compact_edges = [
        {
            "from": e["source"],
            "outcome": e.get("sourceHandle") or "success",
            "to": e["target"],
        }
        for e in edges
        if e.get("source") in managed_ids and e.get("target") in managed_ids
    ]
    return {
        "nodes": compact_nodes,
        "edges": compact_edges,
        "static_attributes": redactor.tokenize_data(static_attributes),
    }


# -- expansion (model -> canvas) -------------------------------------------------------------


def _new_node(
    plan_node: PlanNodeIn, plugin: PluginDefinition, position: dict[str, float]
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": plugin.id,
        "stepUuid": str(uuid.uuid4()),
        "title": plan_node.title or plugin.name,
        "overview": plugin.overview,
        "description": plugin.description,
        "artifactType": plugin.artifact_type,
        "requires": list(plugin.requires),
        "requiresParsed": list(plugin.requires_parsed),
        "produces": list(plugin.produces),
        "producesParsed": list(plugin.produces_parsed),
        "consumes": list(plugin.consumes),
        "outcomes": [{"name": outcome.name} for outcome in plugin.outcomes],
        "pluginConfig": copy.deepcopy(plan_node.config),
    }
    if plan_node.disabled:
        data["disabled"] = True
    return {
        "id": plan_node.id,
        "type": STEP_NODE_TYPE,
        "position": position,
        "zIndex": 1,
        "data": data,
        "measured": {"width": NODE_WIDTH, "height": NODE_HEIGHT},
        "dragging": False,
        "selected": False,
    }


def _updated_node(current: dict[str, Any], plan_node: PlanNodeIn) -> dict[str, Any]:
    node = copy.deepcopy(current)
    data = node["data"]
    if plan_node.title is not None:
        data["title"] = plan_node.title
    data["pluginConfig"] = copy.deepcopy(plan_node.config)
    if plan_node.disabled:
        data["disabled"] = True
    else:
        data.pop("disabled", None)
    return node


def _place(
    new_ids: list[str],
    order: list[str],
    parents: dict[str, list[str]],
    positions: dict[str, dict[str, float]],
) -> None:
    """Position new nodes right of their parents; roots go below everything already placed."""
    for node_id in order:
        if node_id not in new_ids:
            continue
        placed_parents = [positions[p] for p in parents.get(node_id, []) if p in positions]
        if placed_parents:
            x = max(p["x"] for p in placed_parents) + PITCH_X
            y = placed_parents[0]["y"]
        elif positions:
            x = min(p["x"] for p in positions.values())
            y = max(p["y"] for p in positions.values()) + PITCH_Y
        else:
            x, y = 0.0, 0.0
        while any(
            abs(p["x"] - x) < PITCH_X - 40 and abs(p["y"] - y) < PITCH_Y - 40
            for p in positions.values()
        ):
            y += PITCH_Y
        positions[node_id] = {"x": x, "y": y}


def _validated_static_attributes(
    raw: list[dict[str, Any]], errors: list[str]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        try:
            attribute = StaticAttributeDef.model_validate(item)
        except ValidationError as exc:
            errors.append(f"static_attributes[{index}]: {exc.errors()[0]['msg']}")
            continue
        if attribute.name in seen:
            errors.append(f"static_attributes: duplicate name '{attribute.name}'")
        seen.add(attribute.name)
        result.append(attribute.model_dump())
    return result


def _repair_groups(groups: list[dict[str, Any]], node_ids: set[str]) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    for group in groups:
        surviving = [n for n in group.get("nodeIds", []) if n in node_ids]
        if len(surviving) < 2 and group.get("isContainer") is not True:
            continue
        repaired.append({**group, "nodeIds": surviving})
    return repaired


def expand_plan(
    plan: WorkflowPlanIn,
    *,
    current_nodes: list[dict[str, Any]],
    current_edges: list[dict[str, Any]],
    current_groups: list[dict[str, Any]],
    current_static_attributes: list[dict[str, Any]],
    registry: PluginLookup,
) -> ExpandedWorkflow:
    errors: list[str] = []
    current_by_id = {n["id"]: n for n in current_nodes if "id" in n}
    plugins: dict[str, PluginDefinition] = {}

    seen: set[str] = set()
    for plan_node in plan.nodes:
        if plan_node.id in seen:
            errors.append(f"Duplicate node id '{plan_node.id}'")
        seen.add(plan_node.id)
        plugin = registry.get_plugin(plan_node.kind, include_disabled=True)
        if plugin is None:
            errors.append(
                f"Unknown step kind '{plan_node.kind}' (node '{plan_node.id}'); use list_steps"
            )
            continue
        existing = current_by_id.get(plan_node.id)
        if existing is not None and _kind(existing) != plan_node.kind:
            errors.append(
                f"Node '{plan_node.id}' already exists with kind '{_kind(existing)}'; "
                "a node's kind cannot change - give the new step a new id"
            )
            continue
        if not plugin.executable and not (existing is not None and plan_node.kind == FUNNEL_KIND):
            errors.append(
                f"'{plan_node.kind}' is a canvas decoration (node '{plan_node.id}') and cannot be "
                "created by the assistant"
            )
            continue
        plugins[plan_node.id] = plugin

    plan_ids = {n.id for n in plan.nodes}
    edge_keys: set[tuple[str, str, str]] = set()
    for edge in plan.edges:
        if edge.source not in plan_ids or edge.target not in plan_ids:
            missing = edge.source if edge.source not in plan_ids else edge.target
            errors.append(f"Edge {edge.source}->{edge.target} refers to unknown node '{missing}'")
            continue
        if edge.source == edge.target:
            errors.append(f"Edge from '{edge.source}' to itself is not allowed")
            continue
        plugin = plugins.get(edge.source)
        if plugin is not None:
            names = [o.name for o in plugin.outcomes]
            if edge.outcome not in names:
                errors.append(
                    f"Node '{edge.source}' ({plugin.id}) has no outcome '{edge.outcome}'; "
                    f"valid outcomes: {', '.join(names) or 'none'}"
                )
                continue
        key = _edge_key(edge.source, edge.outcome, edge.target)
        if key in edge_keys:
            errors.append(f"Duplicate edge {edge.source} --{edge.outcome}--> {edge.target}")
        edge_keys.add(key)

    order = _topological_order(
        [n.id for n in plan.nodes if n.id in plan_ids],
        [
            (e.source, e.target)
            for e in plan.edges
            if e.source in plan_ids and e.target in plan_ids and e.source != e.target
        ],
    )
    if order is None and not errors:
        errors.append("The edges contain a cycle; a workflow must be acyclic")

    static_attributes = current_static_attributes
    static_changed = False
    if plan.static_attributes is not None:
        validated = _validated_static_attributes(plan.static_attributes, errors)
        static_changed = validated != current_static_attributes
        static_attributes = validated

    if errors:
        raise PlanError(errors)
    if order is None:  # unreachable: a cycle already produced an error above
        raise PlanError(["The edges contain a cycle; a workflow must be acyclic"])

    # -- nodes -----------------------------------------------------------------------------
    plan_by_id = {n.id: n for n in plan.nodes}
    kept: list[dict[str, Any]] = []
    for node in current_nodes:
        node_id = node.get("id")
        if not is_plan_managed(node):
            kept.append(node)
        elif node_id in plan_by_id:
            kept.append(
                node if _kind(node) == FUNNEL_KIND else _updated_node(node, plan_by_id[node_id])
            )
    positions = {
        n["id"]: n["position"]
        for n in kept
        if isinstance(n.get("position"), dict) and "x" in n["position"] and "y" in n["position"]
    }
    new_ids = [n.id for n in plan.nodes if n.id not in current_by_id]
    parents: dict[str, list[str]] = {}
    for edge in plan.edges:
        parents.setdefault(edge.target, []).append(edge.source)
    _place(new_ids, order, parents, positions)
    created = [
        _new_node(plan_by_id[node_id], plugins[node_id], positions[node_id]) for node_id in new_ids
    ]
    nodes = [*kept, *created]

    # -- edges -----------------------------------------------------------------------------
    existing_edges = {
        _edge_key(e["source"], e.get("sourceHandle") or "success", e["target"]): e
        for e in current_edges
        if "source" in e and "target" in e
    }
    managed_current = {n["id"] for n in current_nodes if is_plan_managed(n) and "id" in n}
    edges = [
        e
        for e in current_edges
        if not (e.get("source") in managed_current or e.get("target") in managed_current)
    ]
    for edge in plan.edges:
        key = _edge_key(edge.source, edge.outcome, edge.target)
        edges.append(
            copy.deepcopy(existing_edges[key])
            if key in existing_edges
            else {
                "id": _edge_id(edge.source, edge.outcome, edge.target),
                "type": "waypoint",
                "zIndex": 0,
                "data": {"edgeStyle": "bezier"},
                "source": edge.source,
                "sourceHandle": edge.outcome,
                "target": edge.target,
                "targetHandle": "input",
                "selected": False,
            }
        )

    groups = _repair_groups(current_groups, {n["id"] for n in nodes if "id" in n})
    changes = _summarize(current_nodes, current_edges, nodes, plan, plan_by_id, static_changed)
    return ExpandedWorkflow(
        nodes=nodes,
        edges=edges,
        groups=groups,
        static_attributes=static_attributes,
        changes=changes,
    )


def _title(node: dict[str, Any]) -> str:
    data = _data(node)
    return str(data.get("title") or data.get("kind") or node.get("id"))


def _summarize(
    before_nodes: list[dict[str, Any]],
    before_edges: list[dict[str, Any]],
    after_nodes: list[dict[str, Any]],
    plan: WorkflowPlanIn,
    plan_by_id: dict[str, PlanNodeIn],
    static_changed: bool,
) -> dict[str, Any]:
    before_managed = {n["id"]: n for n in before_nodes if is_plan_managed(n) and "id" in n}
    after_by_id = {n["id"]: n for n in after_nodes if "id" in n}

    added = [
        {
            "id": n.id,
            "kind": n.kind,
            "title": _title(after_by_id[n.id]),
            # Shown to the user before they apply, with secret values masked.
            "config": _config_text(
                redact_secrets_in_data(_data(after_by_id[n.id]).get("pluginConfig") or {})
            ),
        }
        for n in plan.nodes
        if n.id not in before_managed
    ]
    removed = [
        {"id": node_id, "kind": _kind(node), "title": _title(node)}
        for node_id, node in before_managed.items()
        if node_id not in plan_by_id
    ]
    changed: list[dict[str, Any]] = []
    for node_id, node in before_managed.items():
        if node_id not in plan_by_id or _kind(node) == FUNNEL_KIND:
            continue
        old, new = node["data"], after_by_id[node_id]["data"]
        old_config, new_config = old.get("pluginConfig") or {}, new.get("pluginConfig") or {}
        fields = sorted(
            k for k in {*old_config, *new_config} if old_config.get(k) != new_config.get(k)
        )
        if old.get("title") != new.get("title"):
            fields.append("title")
        if bool(old.get("disabled")) != bool(new.get("disabled")):
            fields.append("disabled")
        if fields:
            changed.append(
                {
                    "id": node_id,
                    "kind": _kind(node),
                    "title": _title(after_by_id[node_id]),
                    "fields": fields,
                    "before": _config_text(redact_secrets_in_data(old_config)),
                    "after": _config_text(redact_secrets_in_data(new_config)),
                }
            )

    old_keys = {
        _edge_key(e["source"], e.get("sourceHandle") or "success", e["target"])
        for e in before_edges
        if e.get("source") in before_managed and e.get("target") in before_managed
    }
    new_keys = {_edge_key(e.source, e.outcome, e.target) for e in plan.edges}

    def as_dicts(keys: set[tuple[str, str, str]]) -> list[dict[str, str]]:
        return [{"from": s, "outcome": o, "to": t} for s, o, t in sorted(keys)]

    return {
        "nodes_added": added,
        "nodes_removed": removed,
        "nodes_changed": changed,
        "edges_added": as_dicts(new_keys - old_keys),
        "edges_removed": as_dicts(old_keys - new_keys),
        "static_attributes_changed": static_changed,
    }
