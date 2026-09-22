"""Executor for the collect-statistics debugging step.

Records one job_statistics row per device reaching this node, tagged with
the node's configured `result` — never inferred from DeviceStatus. Wire one
instance to an upstream step's success handle (result=success) and a second
instance to its failure handle (result=failed) to capture both outcomes for
the same job; see doc/WORKFLOW-STEPS.md for why this is a config toggle
rather than auto-detection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.job_statistics_repository import JobStatisticsRepository
from services.artifacts import ArtifactService
from workflow_steps.common.notification_context import resolve_run_workflow

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_VALID_RESULTS = {"success", "failed"}


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    result = str(config.get("result") or "").strip().lower()
    if result not in _VALID_RESULTS:
        raise ValueError(f"collect-statistics: result must be one of {sorted(_VALID_RESULTS)}")

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db, workflow, _owner_username = resolve_run_workflow(run, step_id="collect-statistics")

    logger.info(
        "collect-statistics started run_id=%s node_id=%s devices=%d result=%s",
        run.id,
        node_id,
        len(context.devices),
        result,
    )

    rows = [
        {
            "run_id": run.id,
            "node_id": node_id,
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "device_name": device.name,
            "result": result,
        }
        for device in context.devices.values()
    ]
    created = JobStatisticsRepository(db).create_batch(rows)

    logger.info(
        "collect-statistics finished wrote=%d result=%s run_id=%s",
        len(created),
        result,
        run.id,
    )

    return [
        StepOutcome(
            name="success",
            context=context,
            summary=f"recorded {len(created)} device(s) as {result}",
        )
    ]
