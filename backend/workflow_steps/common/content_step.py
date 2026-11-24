"""The shared runner of the content writers: filter-output, merge-content, update-content.

Each of them reads content a device already has, turns it into new text, stores that as an
artifact and leaves a node-result entry ``parsed[<node>][<kind>]`` that ``content_resolver`` reads
back. Only the transform differs; the device loop, the failure contract, the entry and the
outcomes are written once here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.partial_outcomes import device_error_from_exception

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredContent:
    """What a transform produced for one device."""

    text: str
    media_type: str
    # Keys added to the node-result entry (``match_counts`` of update-content).
    entry: Mapping[str, Any] = field(default_factory=dict)


Transform = Callable[[str, DeviceContext], Awaitable[StoredContent | Fail]]


async def run_content_step(
    context: WorkflowContext,
    *,
    step_id: str,
    node_id: str,
    kind: str,
    transform: Transform,
    artifact_service: ArtifactService,
    metadata_prefix: str,
    metadata: Mapping[str, Any] | None = None,
    code_overrides: Mapping[type[ValueError], str] | None = None,
) -> list[StepOutcome]:
    """Run ``transform`` for every device and store its result as ``kind`` content.

    ``code_overrides`` maps a ``ValueError`` subclass the transform raises to the error code the
    device records (the sentence and the failure record are kept). The step's own counts are
    ``<node>.<metadata_prefix>_success_count`` and ``..._failure_count``; ``metadata`` adds more.
    """
    if not context.devices:
        return [StepOutcome(name="success", context=context)]
    overrides = dict(code_overrides or {})

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        try:
            stored = await transform(device_id, device)
        except tuple(overrides) as exc:
            error = device_error_from_exception(exc, node_id=node_id, step_id=step_id)
            code = next(code for cls, code in overrides.items() if isinstance(exc, cls))
            return Fail(code, error.message, error.failure)
        if isinstance(stored, Fail):
            return stored
        artifact_ref = await artifact_service.store(
            content=stored.text,
            kind=kind,
            device_id=device_id,
            run_id=context.run_id,
            media_type=stored.media_type,
        )
        entry = {
            "artifact_ref": artifact_ref.model_dump(mode="json"),
            "step_node_id": node_id,
            "output_key": kind,
            "size_bytes": len(stored.text.encode("utf-8")),
            "kind": kind,
            **stored.entry,
        }
        return device.model_copy(
            update={
                "parsed": set_node_result(device.parsed, node_id, kind, entry),
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )

    batch = await run_per_device(context, work, node_id=node_id, step_id=step_id)
    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        step_id,
        len(batch.ok),
        len(batch.failed),
        context.run_id,
    )
    return build_outcomes(
        context,
        batch.ok,
        batch.failed,
        metadata={
            **(metadata or {}),
            f"{node_id}.{metadata_prefix}_success_count": len(batch.ok),
            f"{node_id}.{metadata_prefix}_failure_count": len(batch.failed),
        },
    )
