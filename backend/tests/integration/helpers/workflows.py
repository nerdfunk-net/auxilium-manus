"""Build persisted ``Workflow`` / ``WorkflowRun`` rows for StepRunner tests.

Canvas node shape mirrors what the frontend persists and what
``StepRunner._execute_and_persist_node`` reads:
``{"id", "data": {"kind": <step-id>, "title": str, "pluginConfig": dict}}``.
Edges carry ``sourceHandle`` = the upstream outcome name (``success`` / ``failure``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from core.models.runs import WorkflowRun
from core.models.workflows import Workflow


def node(
    node_id: str,
    kind: str,
    config: dict[str, Any] | None = None,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "workflowNode",
        "position": {"x": 0, "y": 0},
        "data": {
            "kind": kind,
            "title": title or kind,
            "pluginConfig": config or {},
        },
    }


def edge(source: str, target: str, *, source_handle: str = "success"):
    return {
        "id": f"{source}->{target}:{source_handle}",
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
    }


def linear_edges(node_ids: list[str], *, source_handle: str = "success") -> list[dict[str, Any]]:
    return [
        edge(a, b, source_handle=source_handle)
        for a, b in zip(node_ids, node_ids[1:], strict=False)
    ]


def build_linear_workflow(
    db: Session,
    *,
    creator_id: int,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    name: str = "itest-workflow",
) -> Workflow:
    """Persist a Workflow with the given canvas graph. Auto-links nodes in a
    straight line on the ``success`` handle when ``edges`` is omitted.
    """
    if edges is None:
        edges = linear_edges([n["id"] for n in nodes])

    workflow = Workflow(
        uuid=str(uuid.uuid4()),
        name=f"{name}-{uuid.uuid4().hex[:8]}",
        creator_id=creator_id,
        canvas_nodes=nodes,
        canvas_edges=edges,
        canvas_groups=[],
        static_attributes=[],
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def make_run(
    db: Session,
    *,
    workflow: Workflow,
    triggered_by_id: int | None,
    device_ids: list[str] | None = None,
    run_mode: str = "normal",
    trigger_type: str = "manual",
) -> WorkflowRun:
    run = WorkflowRun(
        uuid=str(uuid.uuid4()),
        workflow_id=workflow.id,
        triggered_by_id=triggered_by_id,
        status="pending",
        trigger_type=trigger_type,
        run_mode=run_mode,
        device_ids=device_ids or [],
        run_inputs={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
