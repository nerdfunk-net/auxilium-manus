"""What every Batfish step shares when it hands its result on (W7-06, W2-11).

``store_batfish_result`` writes the answer as one JSON artifact and returns the metadata entry
(``{node}.{output_key}``) that points at it; ``batfish_node_device`` is the one way a Batfish node
becomes a ``DeviceContext`` (``source="batfish"``).
"""

from __future__ import annotations

import json
from typing import Any

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import ArtifactService

BATFISH_RESULT_KIND = "batfish_result"
BATFISH_SOURCE = "batfish"


async def store_batfish_result(
    artifact_service: ArtifactService,
    payload: Any,
    *,
    context: WorkflowContext,
    node_id: str,
    question: str,
    **extra: Any,
) -> dict[str, Any]:
    """Store ``payload`` as a ``batfish_result`` artifact; the metadata entry that names it.

    ``extra`` keys (a row count, a verdict, warnings) follow ``artifact_ref`` in the entry.
    """
    artifact_ref = await artifact_service.store(
        content=json.dumps(payload, indent=2, default=str),
        kind=BATFISH_RESULT_KIND,
        device_id=f"batfish-{node_id}",
        run_id=context.run_id,
        media_type="application/json",
    )
    return {
        "kind": BATFISH_RESULT_KIND,
        "question": question,
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        **extra,
    }


def batfish_node_device(node: str, *, parsed: bool = False) -> DeviceContext:
    """A Batfish node as a device; ``parsed`` adds the PARSED capability (the caller fills it)."""
    capabilities = {Capability.IDENTITY}
    if parsed:
        capabilities.add(Capability.PARSED)
    return DeviceContext(
        id=node,
        name=node,
        hostname=node,
        source=BATFISH_SOURCE,
        capabilities=capabilities,
        status=DeviceStatus.OK,
    )
