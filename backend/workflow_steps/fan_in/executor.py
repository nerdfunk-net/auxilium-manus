"""Executor for the fan-in (join) step.

Marks the rejoin boundary after a fanned-out inventory step. By the time this
executor runs, the orchestration layer has already merged the per-device child
workflow contexts into a single context (see
``hatchet/workflows/workflow_run.py`` and
``services/workflow_context/merge.merge_fan_out_contexts``).

The step is therefore a near pass-through: it forwards the merged context
unchanged — preserving every device capability — so that downstream steps such
as ``store-artifact`` or ``git-push`` run exactly once over all devices instead
of once per child workflow.
"""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del config, artifact_service  # unused — fan-in is a pass-through boundary

    device_count = len(context.devices)
    logger.info(
        "fan-in run_id=%s node_id=%s merged_devices=%d",
        run.id,
        node_id,
        device_count,
    )

    metadata = {
        **context.metadata,
        f"{node_id}.fan_in": {"device_count": device_count},
    }
    new_context = context.model_copy(update={"metadata": metadata})
    return [StepOutcome(name="success", context=new_context)]
