"""Response models for browsing/resolving attribute paths from a past run.

Backs the frontend's attribute-path picker/preview (see
doc/WORKFLOW-STEPS.md's filter-segment documentation and
services.workflow_context.attribute_path_discovery for how these are built).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

AttributePathNodeKind = Literal["scalar", "dict", "list"]
AttributeStateLiteral = Literal["absent", "null", "empty", "present"]


class AttributePathNode(BaseModel):
    """One node in a discovered attribute-path tree for a past run.

    Recursive (``children`` references this same model) — the first
    self-referential Pydantic model in this codebase, hence the explicit
    ``model_rebuild()`` call below.
    """

    name: str
    path: str
    kind: AttributePathNodeKind
    example_value: str | None = None
    item_count: int | None = None
    discriminator_warning: str | None = None
    children: list[AttributePathNode] = []


AttributePathNode.model_rebuild()


class AttributePathTreeResponse(BaseModel):
    run_id: int
    # Subset of the requested ancestor node ids that actually had step
    # results in this run (a workflow edited since the run may no longer
    # match 1:1).
    ancestor_node_ids: list[str]
    device_count: int
    nodes: list[AttributePathNode]


class AttributePathResolveRequest(BaseModel):
    path: str
    ancestor_node_ids: list[str] = []


class AttributePathResolveResult(BaseModel):
    device_id: str
    device_name: str
    state: AttributeStateLiteral
    value: str | None


class AttributePathResolveResponse(BaseModel):
    run_id: int
    results: list[AttributePathResolveResult]
