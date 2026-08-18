"""Executor for the notify-on-error shared error-sink step.

Meant as a single downstream node that many upstream steps' ``failure``
outcome handles fan into, instead of a dedicated notify node after every
step. Writes one notification row per accumulated ``DeviceError`` on each
device in context, so a device that failed at more than one point before
reaching this node still surfaces every root cause, not just the latest.
"""

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
from workflow_steps.notify_on_error.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_SEVERITY = "error"


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
        raise ValueError("notify-on-error: message is required")

    db, workflow, owner_username = resolve_run_workflow(run, step_id="notify-on-error")

    logger.info(
        "notify-on-error node_id=%s devices=%d",
        node_id,
        len(context.devices),
    )

    rows: list[dict[str, Any]] = []
    device_logs: dict[str, dict[str, Any]] = {}
    for device_id, device in context.devices.items():
        if not device.errors:
            continue

        rendered_messages: list[str] = []
        for error in device.errors:
            rendered = render_placeholder_template(message, device, error=error)
            rendered_messages.append(rendered)
            rows.append(
                {
                    "run_id": run.id,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "workflow_owner_username": owner_username,
                    "device_name": device.name,
                    "severity": _SEVERITY,
                    "message": rendered,
                }
            )

        device_logs[device_id] = {
            "device_id": device_id,
            "device_name": device.name,
            "error_count": len(device.errors),
            "messages": rendered_messages,
        }

    created = NotificationRepository(db).create_batch(rows)

    debug_logs = {
        "message": message,
        "severity": _SEVERITY,
        "device_count": len(device_logs),
        "notification_count": len(created),
        "devices": device_logs,
    }
    metadata = {
        **context.metadata,
        f"{node_id}{DEBUG_LOGS_METADATA_SUFFIX}": debug_logs,
    }

    logger.info(
        "notify-on-error node_id=%s devices=%d wrote=%d notifications",
        node_id,
        len(device_logs),
        len(created),
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"notified {len(created)} error(s) across {len(device_logs)} device(s)",
        )
    ]
