"""The stamp that pins an Ask the Net release to the version that was reviewed.

A release (doc/AI_TOOL_CHAIN.md §16) is a promise about a definition, not about a row: what the
workflow does, which inputs it takes, and what the releaser said about it. The stamp is a hash of
all of that, **including every workflow it starts with a ``start-workflow`` step**, so editing a
child ends the parent's release without anyone having to find the parents. It is stored when the
workflow is released, recomputed whenever the release is used, and carried in the signed proposal.
A release counts only while the stored stamp equals the recomputed one, which makes the
clear-on-edit rule a convenience instead of the only safeguard: a save that races a release, a
child edit and a stale confirmation all fail the comparison.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Iterable
from typing import Any

# A release can pin at most this many workflows (the root and everything it starts). A wider graph
# is refused rather than pinned in part: a partial pin would leave the workflows past the cap free
# to change under a release that still looks current.
MAX_STAMPED_WORKFLOWS = 50
_START_WORKFLOW_KIND = "start-workflow"


# A workflow row (or anything with ``id``, ``canvas_nodes``, ``canvas_edges``, ``canvas_groups`` and
# ``static_attributes``). Untyped on purpose: SQLAlchemy ``Mapped`` columns do not satisfy a
# structural Protocol under pyright, and the stamp only reads those five attributes.
_Definition = Any

WorkflowLoader = Callable[[int], _Definition | None]


class ReleaseTooLargeError(ValueError):
    """The workflow starts more workflows than a release can pin."""


def release_settings(workflow: Any) -> dict[str, Any]:
    """What the releaser decided; part of the stamp so a changed release is a different release."""
    return {
        "description": (workflow.ai_description or "").strip(),
        "result_node_id": workflow.ai_result_node_id,
        "devices_input": workflow.ai_devices_input,
        "credential_inputs": sorted(workflow.ai_credential_inputs or []),
        "allow_free_ip": bool(workflow.ai_allow_free_ip),
    }


def _definition(workflow: _Definition) -> dict[str, Any]:
    return {
        "nodes": workflow.canvas_nodes or [],
        "edges": workflow.canvas_edges or [],
        "groups": workflow.canvas_groups or [],
        "inputs": workflow.static_attributes or [],
    }


def _as_id(raw: Any) -> int | None:
    try:
        value = int(raw)
    except TypeError, ValueError:
        return None
    return value if value > 0 else None


def child_workflow_ids(nodes: Iterable[Any]) -> list[int]:
    """Ids of the workflows the canvas starts. Disabled steps count: enabling one is an edit of
    the parent only if it changes the parent's stamp, and it does."""
    found: list[int] = []
    for node in nodes or []:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict) or data.get("kind") != _START_WORKFLOW_KIND:
            continue
        workflow_id = _as_id((data.get("pluginConfig") or {}).get("workflow_id"))
        if workflow_id is not None:
            found.append(workflow_id)
    return found


def _collect(root: _Definition, load: WorkflowLoader) -> dict[int, dict[str, Any] | None]:
    """The definition of every workflow reachable from ``root`` (``None`` for a missing one).

    Raises ``ReleaseTooLargeError`` when more than ``MAX_STAMPED_WORKFLOWS`` are reachable."""
    seen: dict[int, dict[str, Any] | None] = {root.id: _definition(root)}
    queue = child_workflow_ids(root.canvas_nodes or [])
    while queue:
        workflow_id = queue.pop(0)
        if workflow_id in seen:
            continue
        if len(seen) >= MAX_STAMPED_WORKFLOWS:
            raise ReleaseTooLargeError(
                f"The workflow starts more than {MAX_STAMPED_WORKFLOWS - 1} other workflows"
            )
        child = load(workflow_id)
        seen[workflow_id] = None if child is None else _definition(child)
        if child is not None:
            queue.extend(child_workflow_ids(child.canvas_nodes or []))
    return seen


def compute_stamp(root: _Definition, settings: dict[str, Any], load: WorkflowLoader) -> str:
    """Hex SHA-256 over the root, its release settings and every workflow it starts."""
    payload = {
        "settings": settings,
        "workflows": {str(key): value for key, value in sorted(_collect(root, load).items())},
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def release_is_current(workflow: Any, load: WorkflowLoader) -> bool:
    """True while the workflow is released and nothing it is made of has changed since."""
    stored = getattr(workflow, "ai_release_stamp", None)
    if not workflow.ai_released or not stored:
        return False
    try:
        current = compute_stamp(workflow, release_settings(workflow), load)
    except ReleaseTooLargeError:
        return False
    return hmac.compare_digest(stored, current)
