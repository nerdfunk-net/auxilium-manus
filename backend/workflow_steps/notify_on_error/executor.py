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
from models.failure import FailureInfo, failure_from_exception, failure_to_json
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.mattermost.common.exceptions import MattermostAPIError
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.common.failure_records import TRANSPORT_FAILED
from workflow_steps.common.mattermost_source import resolve_mattermost_credentials
from workflow_steps.common.notification_context import resolve_run_workflow, write_notifications
from workflow_steps.common.notification_target import parse_mattermost_target
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag, require_text
from workflow_steps.notify_on_error.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "notify-on-error"
_SEVERITY = "error"


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

    max_messages = parse_int_flag(
        config, "max_messages", default=int(defaults["max_messages"]), step_id=_STEP_ID
    )
    notify_local = parse_bool_flag(config, "notify_local", default=True)
    notify_mattermost = parse_bool_flag(config, "notify_mattermost", default=False)
    if not notify_local and not notify_mattermost:
        raise ValueError(
            f"{_STEP_ID}: enable at least one notification channel (local or Mattermost)"
        )

    target = parse_mattermost_target(config, step_id=_STEP_ID) if notify_mattermost else None

    workflow, owner_username = resolve_run_workflow(run, step_id=_STEP_ID)

    logger.info(
        "%s node_id=%s devices=%d",
        _STEP_ID,
        node_id,
        len(context.devices),
    )

    mattermost_client = None
    mattermost_credentials = None
    mattermost_channel_id: str | None = None
    # Policy (D11): a configuration error (unknown source) raises, also when no device failed, so
    # a wrong source does not stay hidden until a real failure; a transport error is recorded and
    # the notification step still succeeds (an error sink must not fail while reporting one).
    mattermost_failure: FailureInfo | None = None
    if target is not None:
        mattermost_credentials = resolve_mattermost_credentials(
            require_session(run, _STEP_ID), target.source_id, step_id=_STEP_ID
        )
        if any(device.errors for device in context.devices.values()):
            mattermost_client = service_factory.get_mattermost_app_service()
            try:
                channel = await mattermost_client.get_channel_by_name(
                    mattermost_credentials, target.team_name, target.channel_name
                )
                mattermost_channel_id = channel["id"]
            except MattermostAPIError as exc:
                mattermost_failure = failure_from_exception(exc) or TRANSPORT_FAILED
                logger.warning(
                    "%s: Mattermost channel %s/%s unavailable, skipping: %s",
                    _STEP_ID,
                    target.team_name,
                    target.channel_name,
                    exc,
                )

    rows: list[dict[str, Any]] = []
    device_logs: dict[str, dict[str, Any]] = {}
    mattermost_posted = 0
    mattermost_failed = 0
    # Mattermost throttles bursts: after max_messages posts the rest are only counted and
    # summarised in one final post. The local notification rows are not capped.
    post_budget = max_messages
    suppressed = 0
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
                        "node_id": node_id,
                        "workflow_id": workflow.id,
                        "workflow_name": workflow.name,
                        "workflow_owner_username": owner_username,
                        "device_name": device.name,
                        "severity": _SEVERITY,
                        "message": rendered,
                    }
                )

            if (
                not mattermost_channel_id
                or mattermost_client is None
                or mattermost_credentials is None
            ):
                continue
            if post_budget <= 0:
                suppressed += 1
                continue
            post_budget -= 1
            try:
                await mattermost_client.create_post(
                    mattermost_credentials, mattermost_channel_id, rendered
                )
                mattermost_posted += 1
            except MattermostAPIError as exc:
                mattermost_failed += 1
                mattermost_failure = failure_from_exception(exc) or TRANSPORT_FAILED
                logger.warning(
                    "%s: could not post to %s/%s: %s",
                    _STEP_ID,
                    target.team_name if target else "",
                    target.channel_name if target else "",
                    exc,
                )

        device_logs[device_id] = {
            "device_id": device_id,
            "device_name": device.name,
            "error_count": len(device.errors),
            "messages": rendered_messages,
        }

    if (
        mattermost_channel_id
        and mattermost_client is not None
        and mattermost_credentials is not None
        and suppressed
    ):
        try:
            await mattermost_client.create_post(
                mattermost_credentials,
                mattermost_channel_id,
                f"{suppressed} further error(s) in this run were not posted individually; "
                "see the run page.",
            )
        except MattermostAPIError as exc:
            mattermost_failure = failure_from_exception(exc) or TRANSPORT_FAILED
            logger.warning(
                "%s: could not post the summary to %s/%s: %s",
                _STEP_ID,
                target.team_name if target else "",
                target.channel_name if target else "",
                exc,
            )

    created = write_notifications(run_id=run.id, node_id=node_id, rows=rows) if notify_local else 0

    debug_logs = {
        "message": message,
        "severity": _SEVERITY,
        "device_count": len(device_logs),
        "notification_count": created,
        "devices": device_logs,
        "mattermost_enabled": notify_mattermost,
        "mattermost_posted": mattermost_posted,
        "mattermost_failed": mattermost_failed,
        "mattermost_suppressed": suppressed,
        "mattermost_failure": failure_to_json(mattermost_failure),
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
        created,
        mattermost_posted,
        mattermost_failed,
    )

    summary = f"notified {created} error(s) across {len(device_logs)} device(s)"
    if notify_mattermost:
        summary += f" ({mattermost_posted} posted to Mattermost)"

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=summary,
        )
    ]
