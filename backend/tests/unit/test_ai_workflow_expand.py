"""Compact plan -> persisted canvas expansion, merge onto the current canvas, change summary."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from core.config import settings
from repositories.plugin_repository import PluginRepository
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.workflow_expand import (
    PlanError,
    WorkflowPlanIn,
    build_compact_view,
    expand_plan,
)
from services.plugin_registry.plugin_registry_service import PluginRegistryService


@pytest.fixture(scope="module")
def registry() -> PluginRegistryService:
    return PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))


def _plan(nodes: list[dict], edges: list[dict] | None = None, **extra: Any) -> WorkflowPlanIn:
    return WorkflowPlanIn.model_validate({"nodes": nodes, "edges": edges or [], **extra})


def _expand(registry, plan, current=None):
    current = current or {}
    return expand_plan(
        plan,
        current_nodes=current.get("nodes", []),
        current_edges=current.get("edges", []),
        current_groups=current.get("groups", []),
        current_static_attributes=current.get("static_attributes", []),
        registry=registry,
    )


TWO_STEPS = [
    {"id": "inv", "kind": "get-nautobot-devices", "config": {"nautobot_source_id": "nautobot"}},
    {"id": "attrs", "kind": "get-nautobot-attributes", "title": "Attrs"},
]
CHAIN = [{"from": "inv", "outcome": "success", "to": "attrs"}]


def test_new_nodes_get_the_full_persisted_shape_from_the_registry(registry) -> None:
    result = _expand(registry, _plan(TWO_STEPS, CHAIN))

    node = next(n for n in result.nodes if n["id"] == "inv")
    assert node["type"] == "workflowNode"
    assert node["measured"] == {"width": 320, "height": 128}
    assert node["data"]["kind"] == "get-nautobot-devices"
    assert node["data"]["title"] == "Get from Nautobot"
    assert node["data"]["produces"] == ["identity"]
    assert [o["name"] for o in node["data"]["outcomes"]] == ["success", "failure"]
    assert node["data"]["pluginConfig"] == {"nautobot_source_id": "nautobot"}
    assert node["data"]["stepUuid"]
    assert {"x", "y"} <= set(node["position"])


def test_edges_use_the_persisted_id_and_handle_scheme(registry) -> None:
    result = _expand(registry, _plan(TWO_STEPS, CHAIN))

    edge = result.edges[0]
    assert edge["source"] == "inv" and edge["sourceHandle"] == "success"
    assert edge["target"] == "attrs" and edge["targetHandle"] == "input"
    assert edge["type"] == "waypoint" and edge["data"] == {"edgeStyle": "bezier"}
    assert edge["id"] == "xy-edge__invsuccess-attrsinput"


def test_a_chain_is_laid_out_left_to_right_without_overlap(registry) -> None:
    result = _expand(registry, _plan(TWO_STEPS, CHAIN))

    positions = {n["id"]: n["position"] for n in result.nodes}
    assert positions["attrs"]["x"] > positions["inv"]["x"]


def test_existing_nodes_keep_position_uuid_and_untouched_fields(registry) -> None:
    first = _expand(registry, _plan(TWO_STEPS, CHAIN))
    moved = copy.deepcopy(first.nodes)
    moved[0]["position"] = {"x": 999.5, "y": 123.25}
    current = {"nodes": moved, "edges": first.edges}
    updated_plan = _plan(
        [
            {**TWO_STEPS[0], "config": {"nautobot_source_id": "other"}},
            TWO_STEPS[1],
        ],
        CHAIN,
    )

    result = _expand(registry, updated_plan, current)

    node = next(n for n in result.nodes if n["id"] == "inv")
    assert node["position"] == {"x": 999.5, "y": 123.25}
    assert node["data"]["stepUuid"] == moved[0]["data"]["stepUuid"]
    assert node["data"]["pluginConfig"] == {"nautobot_source_id": "other"}
    assert result.edges[0] == first.edges[0]  # unchanged edge object is reused


def test_a_new_node_is_placed_next_to_its_parent_in_an_existing_canvas(registry) -> None:
    first = _expand(registry, _plan(TWO_STEPS, CHAIN))
    plan = _plan(
        [*TWO_STEPS, {"id": "cfg", "kind": "get-device-configs"}],
        [*CHAIN, {"from": "attrs", "outcome": "success", "to": "cfg"}],
    )

    result = _expand(registry, plan, {"nodes": first.nodes, "edges": first.edges})

    parent = next(n for n in result.nodes if n["id"] == "attrs")
    child = next(n for n in result.nodes if n["id"] == "cfg")
    assert child["position"]["x"] > parent["position"]["x"]


def test_decorations_and_unmanaged_nodes_pass_through_untouched(registry) -> None:
    first = _expand(registry, _plan(TWO_STEPS, CHAIN))
    label = {
        "id": "label-1",
        "type": "labelNode",
        "position": {"x": 1, "y": 2},
        "data": {"kind": "label", "title": "T"},
    }
    current = {"nodes": [*first.nodes, label], "edges": first.edges}

    result = _expand(registry, _plan(TWO_STEPS, CHAIN), current)

    assert label in result.nodes


def test_removed_nodes_drop_their_edges_and_dissolve_small_groups(registry) -> None:
    first = _expand(registry, _plan(TWO_STEPS, CHAIN))
    group = {
        "id": "group-1",
        "title": "G",
        "nodeIds": ["inv", "attrs"],
        "position": {"x": 0, "y": 0},
    }
    current = {"nodes": first.nodes, "edges": first.edges, "groups": [group]}

    result = _expand(registry, _plan([TWO_STEPS[0]]), current)

    assert [n["id"] for n in result.nodes] == ["inv"]
    assert result.edges == []
    assert result.groups == []  # one member left: the group dissolves
    assert result.changes["nodes_removed"][0]["id"] == "attrs"
    assert result.changes["edges_removed"] == [{"from": "inv", "outcome": "success", "to": "attrs"}]


@pytest.mark.parametrize(
    ("nodes", "edges", "fragment"),
    [
        ([{"id": "a", "kind": "no-such-step"}], [], "Unknown step kind"),
        ([{"id": "a", "kind": "label"}], [], "decoration"),
        (TWO_STEPS, [{"from": "inv", "outcome": "nope", "to": "attrs"}], "outcome"),
        (TWO_STEPS, [{"from": "inv", "outcome": "success", "to": "ghost"}], "unknown node"),
        (TWO_STEPS, [{"from": "attrs", "outcome": "success", "to": "attrs"}], "itself"),
        (
            TWO_STEPS,
            [
                {"from": "inv", "outcome": "success", "to": "attrs"},
                {"from": "attrs", "outcome": "success", "to": "inv"},
            ],
            "cycle",
        ),
        ([TWO_STEPS[0], {**TWO_STEPS[0]}], [], "Duplicate node id"),
    ],
)
def test_invalid_plans_are_rejected_with_actionable_messages(
    registry, nodes, edges, fragment
) -> None:
    with pytest.raises(PlanError) as info:
        _expand(registry, _plan(nodes, edges))

    assert any(fragment.lower() in message.lower() for message in info.value.messages)


def test_a_changed_kind_for_an_existing_id_is_rejected(registry) -> None:
    first = _expand(registry, _plan(TWO_STEPS, CHAIN))
    swapped = [{**TWO_STEPS[0], "kind": "get-git-devices"}, TWO_STEPS[1]]

    with pytest.raises(PlanError) as info:
        _expand(registry, _plan(swapped, CHAIN), {"nodes": first.nodes, "edges": first.edges})

    assert "kind" in " ".join(info.value.messages)


def test_changes_summary_lists_added_changed_and_removed(registry) -> None:
    first = _expand(registry, _plan(TWO_STEPS, CHAIN))
    plan = _plan(
        [
            {**TWO_STEPS[0], "config": {"nautobot_source_id": "other"}},
            {"id": "cfg", "kind": "get-device-configs"},
        ],
        [{"from": "inv", "outcome": "success", "to": "cfg"}],
    )

    result = _expand(registry, plan, {"nodes": first.nodes, "edges": first.edges})

    changes = result.changes
    assert [n["id"] for n in changes["nodes_added"]] == ["cfg"]
    assert [n["id"] for n in changes["nodes_removed"]] == ["attrs"]
    changed = changes["nodes_changed"][0]
    assert changed["id"] == "inv" and "nautobot_source_id" in changed["before"]
    assert "other" in changed["after"]
    assert changes["edges_added"] == [{"from": "inv", "outcome": "success", "to": "cfg"}]


def test_static_attributes_are_validated_and_only_replaced_when_given(registry) -> None:
    current = {"static_attributes": [{"name": "keep", "type": "string", "required": False}]}

    untouched = _expand(registry, _plan(TWO_STEPS, CHAIN), current)
    replaced = _expand(
        registry,
        _plan(TWO_STEPS, CHAIN, static_attributes=[{"name": "vlan", "type": "number"}]),
        current,
    )

    assert untouched.static_attributes == current["static_attributes"]
    assert replaced.static_attributes[0]["name"] == "vlan"
    assert replaced.changes["static_attributes_changed"] is True
    with pytest.raises(PlanError):
        _expand(
            registry,
            _plan(TWO_STEPS, CHAIN, static_attributes=[{"name": "r", "type": "reference"}]),
        )


# -- compact view for the model --------------------------------------------------------------


def test_compact_view_hides_layout_noise_and_tokenises_secrets(registry) -> None:
    first = _expand(
        registry,
        _plan(
            [
                {
                    "id": "inv",
                    "kind": "get-nautobot-devices",
                    "config": {"nautobot_source_id": "nautobot", "password": "hunter2hunter2"},
                }
            ]
        ),
    )
    label = {"id": "label-1", "type": "labelNode", "position": {}, "data": {"kind": "label"}}

    view = build_compact_view([*first.nodes, label], [], [], Redactor())

    assert view["nodes"] == [
        {
            "id": "inv",
            "kind": "get-nautobot-devices",
            "title": "Get from Nautobot",
            "config": {"nautobot_source_id": "nautobot", "password": "__SECRET_1__"},
        }
    ]
    assert "hunter2" not in str(view)
    assert "position" not in str(view) and "measured" not in str(view)
