"""WorkflowService must reject cyclic canvas graphs at save time.
See doc/FABLE-ANALYSIS.md §4.2."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import ValidationFailedError
from models.workflows import WorkflowCreate
from services.workflow.workflow_service import WorkflowService, _validate_stop_here_not_in_fan_out


def _cyclic_nodes_and_edges() -> tuple[list[dict], list[dict]]:
    nodes = [
        {"id": "a", "data": {"kind": "log-message"}},
        {"id": "b", "data": {"kind": "log-message"}},
    ]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    return nodes, edges


def test_create_workflow_rejects_cyclic_graph() -> None:
    service = WorkflowService(MagicMock())
    nodes, edges = _cyclic_nodes_and_edges()
    data = WorkflowCreate(
        name="cyclic",
        canvas_nodes=nodes,
        canvas_edges=edges,
    )

    with pytest.raises(ValidationFailedError) as exc_info:
        service.create_workflow(data, user_id=1)

    assert exc_info.value.status_code == 400
    assert "cycle" in exc_info.value.detail.lower()


def _fan_out_branch_with_stop_here() -> tuple[list[dict], list[dict]]:
    # inv (fan-out enabled) -> a -> stop-here -> join -> b
    nodes = [
        {
            "id": "inv",
            "data": {
                "kind": "get-nautobot-devices",
                "pluginConfig": {"fan_out": {"enabled": True, "mode": "per_device"}},
            },
        },
        {"id": "a", "data": {"kind": "get-device-configs"}},
        {"id": "stop", "data": {"kind": "stop-here"}},
        {"id": "join", "data": {"kind": "fan-in"}},
        {"id": "b", "data": {"kind": "log-message"}},
    ]
    edges = [
        {"source": "inv", "target": "a"},
        {"source": "a", "target": "stop"},
        {"source": "stop", "target": "join"},
        {"source": "join", "target": "b"},
    ]
    return nodes, edges


def test_create_workflow_rejects_stop_here_inside_fan_out_branch() -> None:
    service = WorkflowService(MagicMock())
    nodes, edges = _fan_out_branch_with_stop_here()
    data = WorkflowCreate(name="stop-in-fan-out", canvas_nodes=nodes, canvas_edges=edges)

    with pytest.raises(ValidationFailedError) as exc_info:
        service.create_workflow(data, user_id=1)

    assert exc_info.value.status_code == 400
    assert "stop here" in exc_info.value.detail.lower()
    assert "fan-out" in exc_info.value.detail.lower()


def test_validate_stop_here_allows_placement_outside_fan_out_branch() -> None:
    # Same fan-out setup, but stop-here sits after the join — no longer
    # inside the fanned-out branch. Exercises the pure validator directly
    # (create_workflow's happy path needs a real repo, out of scope here).
    nodes = [
        {
            "id": "inv",
            "data": {
                "kind": "get-nautobot-devices",
                "pluginConfig": {"fan_out": {"enabled": True, "mode": "per_device"}},
            },
        },
        {"id": "a", "data": {"kind": "get-device-configs"}},
        {"id": "join", "data": {"kind": "fan-in"}},
        {"id": "stop", "data": {"kind": "stop-here"}},
    ]
    edges = [
        {"source": "inv", "target": "a"},
        {"source": "a", "target": "join"},
        {"source": "join", "target": "stop"},
    ]

    _validate_stop_here_not_in_fan_out(nodes, edges)  # must not raise
