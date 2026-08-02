"""Executor for the show-summary debugging step.

Pass-through marker step: the device x step status table it renders is built
entirely by the frontend from the run's already-fetched
``WorkflowStepResult`` list (see ``step-summary-matrix.ts``), so the
executor itself does not need to look at run history — it just forwards the
incoming context unchanged, like ``fan-in``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del config, artifact_service

    logger.info("show-summary started run_id=%s node_id=%s", run.id, node_id)

    device_count = len(context.devices)
    logger.info(
        "show-summary finished run_id=%s node_id=%s devices=%d",
        run.id,
        node_id,
        device_count,
    )

    metadata = {
        **context.metadata,
        f"{node_id}.show_summary": {"device_count": device_count},
    }
    new_context = context.model_copy(update={"metadata": metadata})
    return [StepOutcome(name="success", context=new_context)]
