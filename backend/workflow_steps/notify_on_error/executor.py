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

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.notification_repository import NotificationRepository
from services.artifacts import ArtifactService
from services.mattermost.common.exceptions import MattermostAPIError
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.common.mattermost_source import resolve_mattermost_credentials
from workflow_steps.common.notification_context import resolve_run_workflow
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.notify_on_error.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "notify-on-error"
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

    defaults = _default_config()
    message = str(config.get("message") or defaults["message"] or "").strip()
    if not message:
        raise ValueError(f"{_STEP_ID}: message is required")

    notify_local = bool(config.get("notify_local", True))
    notify_mattermost = bool(config.get("notify_mattermost", False))
    if not notify_local and not notify_mattermost:
        raise ValueError(
            f"{_STEP_ID}: enable at least one notification channel (local or Mattermost)"
        )

    mattermost_source_id = str(config.get("mattermost_source_id") or "").strip()
    team_name = str(config.get("team_name") or "").strip()
    channel_name = str(config.get("channel_name") or "").strip()
    if notify_mattermost:
        if not mattermost_source_id:
            raise ValueError(f"{_STEP_ID}: mattermost_source_id is not configured")
        if not team_name:
            raise ValueError(f"{_STEP_ID}: team_name is not configured")
        if not channel_name:
            raise ValueError(f"{_STEP_ID}: channel_name is not configured")

    db, workflow, owner_username = resolve_run_workflow(run, step_id=_STEP_ID)

    logger.info(
        "%s node_id=%s devices=%d",
        _STEP_ID,
        node_id,
        len(context.devices),
    )

    mattermost_client = None
    mattermost_credentials = None
    mattermost_channel_id: str | None = None
    if notify_mattermost and any(device.errors for device in context.devices.values()):
        mattermost_client = service_factory.get_mattermost_app_service()
        try:
            mattermost_credentials = resolve_mattermost_credentials(
                db, mattermost_source_id, step_id=_STEP_ID
            )
            channel = await mattermost_client.get_channel_by_name(
                mattermost_credentials, team_name, channel_name
            )
            mattermost_channel_id = channel["id"]
        except (ValueError, MattermostAPIError) as exc:
            logger.warning(
                "%s: Mattermost channel %s/%s unavailable, skipping: %s",
                _STEP_ID,
                team_name,
                channel_name,
                exc,
            )

    rows: list[dict[str, Any]] = []
    device_logs: dict[str, dict[str, Any]] = {}
    mattermost_posted = 0
    mattermost_failed = 0
    for device_id, device in context.devices.items():
        if not device.errors:
            continue

        rendered_messages: list[str] = []
        for error in device.errors:
            rendered = render_placeholder_template(message, device, error=error)
            rendered_messages.append(rendered)
            if notify_local:
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

            if mattermost_channel_id:
                try:
                    await mattermost_client.create_post(
                        mattermost_credentials, mattermost_channel_id, rendered
                    )
                    mattermost_posted += 1
                except MattermostAPIError as exc:
                    mattermost_failed += 1
                    logger.warning(
                        "%s: could not post to %s/%s: %s", _STEP_ID, team_name, channel_name, exc
                    )

        device_logs[device_id] = {
            "device_id": device_id,
            "device_name": device.name,
            "error_count": len(device.errors),
            "messages": rendered_messages,
        }

    created = NotificationRepository(db).create_batch(rows) if notify_local else []

    debug_logs = {
        "message": message,
        "severity": _SEVERITY,
        "device_count": len(device_logs),
        "notification_count": len(created),
        "devices": device_logs,
        "mattermost_enabled": notify_mattermost,
        "mattermost_posted": mattermost_posted,
        "mattermost_failed": mattermost_failed,
    }
    metadata = {
        **context.metadata,
        f"{node_id}{DEBUG_LOGS_METADATA_SUFFIX}": debug_logs,
    }

    logger.info(
        "%s node_id=%s devices=%d wrote=%d notifications mattermost_posted=%d mattermost_failed=%d",
        _STEP_ID,
        node_id,
        len(device_logs),
        len(created),
        mattermost_posted,
        mattermost_failed,
    )

    summary = f"notified {len(created)} error(s) across {len(device_logs)} device(s)"
    if notify_mattermost:
        summary += f" ({mattermost_posted} posted to Mattermost)"

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=summary,
        )
    ]
