"""Executor for the notify debugging step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.notification_repository import NotificationRepository
from services.artifacts import ArtifactService
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.common.notification_context import resolve_run_workflow
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.common.step_flags import require_text
from workflow_steps.notify.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "notify"
_VALID_SEVERITIES = {"info", "warning", "error"}
# At most this many rows per execution, then one row that says how many devices were left out.
MAX_NOTIFICATIONS_PER_STEP = 100


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

    defaults = get_config()
    message = require_text(config, "message", step_id=_STEP_ID, default=defaults["message"])

    severity = str(config.get("severity") or defaults["severity"] or "").strip().lower()
    if severity not in _VALID_SEVERITIES:
        raise ValueError(f"notify: invalid severity {severity!r}")

    db, workflow, owner_username = resolve_run_workflow(run, step_id="notify")

    logger.info(
        "notify node_id=%s severity=%s devices=%d",
        node_id,
        severity,
        len(context.devices),
    )

    rows: list[dict[str, Any]] = []
    device_logs: dict[str, dict[str, Any]] = {}
    for index, (device_id, device) in enumerate(context.devices.items()):
        rendered = render_placeholder_template(message, device)
        if index < MAX_NOTIFICATIONS_PER_STEP:
            rows.append(
                {
                    "run_id": run.id,
                    "node_id": node_id,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "workflow_owner_username": owner_username,
                    "device_name": device.name,
                    "severity": severity,
                    "message": rendered,
                }
            )
        device_logs[device_id] = {
            "device_id": device_id,
            "device_name": device.name,
            "message": rendered,
        }

    omitted = len(context.devices) - MAX_NOTIFICATIONS_PER_STEP
    if omitted > 0:
        rows.append(
            {
                "run_id": run.id,
                    "node_id": node_id,
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "workflow_owner_username": owner_username,
                "device_name": None,
                "severity": severity,
                "message": f"... and {omitted} more devices",
            }
        )

    created = NotificationRepository(db).replace_for_node(
        run_id=run.id, node_id=node_id, rows=rows
    )

    debug_logs = {
        "message": message,
        "severity": severity,
        "device_count": len(device_logs),
        "devices": device_logs,
    }
    metadata = {
        **context.metadata,
        f"{node_id}{DEBUG_LOGS_METADATA_SUFFIX}": debug_logs,
    }

    logger.info("notify node_id=%s wrote=%d notifications", node_id, len(created))

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"notified {len(created)} device(s) at {severity}: {message!r}",
        )
    ]
