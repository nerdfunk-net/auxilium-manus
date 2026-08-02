"""WorkflowService must reject cyclic canvas graphs at save time.
See doc/FABLE-ANALYSIS.md §4.2."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from models.workflows import WorkflowCreate
from services.workflow.workflow_service import WorkflowService


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

    with pytest.raises(HTTPException) as exc_info:
        service.create_workflow(data, user_id=1)

    assert exc_info.value.status_code == 400
    assert "cycle" in exc_info.value.detail.lower()
