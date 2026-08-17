"""Executor for the notify debugging step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.notification_repository import NotificationRepository
from repositories.workflow_repository import WorkflowRepository
from services.artifacts import ArtifactService
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.notify.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {"info", "warning", "error"}


def _default_config() -> dict[str, Any]:
    return get_config()


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

    message = str(config.get("message") or _default_config()["message"] or "").strip()
    if not message:
        raise ValueError("notify: message is required")

    severity = str(config.get("severity") or _default_config()["severity"] or "").strip().lower()
    if severity not in _VALID_SEVERITIES:
        raise ValueError(f"notify: invalid severity {severity!r}")

    db = object_session(run)
    if db is None:
        raise RuntimeError("notify: WorkflowRun has no active DB session")

    result = WorkflowRepository(db).get_by_id(run.workflow_id)
    if result is None:
        raise ValueError(f"notify: workflow {run.workflow_id} not found")
    workflow, owner_username = result

    logger.info(
        "notify node_id=%s severity=%s devices=%d",
        node_id,
        severity,
        len(context.devices),
    )

    rows: list[dict[str, Any]] = []
    device_logs: dict[str, dict[str, Any]] = {}
    for device_id, device in context.devices.items():
        rendered = render_placeholder_template(message, device)
        rows.append(
            {
                "run_id": run.id,
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

    created = NotificationRepository(db).create_batch(rows)

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
