"""Executor for the notify-mattermost step.

Posts one message per step execution to a Mattermost channel, resolved via a
configured Mattermost source, team name, and channel name. ``message``
supports two run-level placeholders that don't come from any single device
-- ``{devices}`` (comma-joined device names) and ``{device_count}`` -- plus
``{path.to.value}`` placeholders resolved per device (same mechanism as
``notify``/``log-message``). When the message contains a per-device
placeholder and ``context.devices`` holds more than one device, the
template is rendered once per device and the results are newline-joined
into that single post, so a multi-device outcome (e.g. several devices
matching a comparison) doesn't silently collapse to just the first device.

When the message contains a per-device placeholder but ``context.devices``
is empty (e.g. this node is wired to an outcome, such as compare-data's
``mismatch`` handle, that legitimately matched zero devices this run), the
step skips posting entirely rather than sending a message with the
placeholder left unresolved -- there's nothing to report. A message with
only run-level placeholders (or no placeholders at all) always posts,
even with zero devices.

Outcomes: ``failure`` is emitted (context unchanged) when the Mattermost
source can't be resolved, the channel lookup fails, or the post itself
fails — a condition that isn't specific to any one device. There is no
per-device success/failure split since this step only ever makes one
network call (or none, when skipped).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.mattermost.common.exceptions import MattermostAPIError
from workflow_steps.common.mattermost_source import resolve_mattermost_credentials
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.notify_mattermost.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "notify-mattermost"


def _default_config() -> dict[str, Any]:
    return get_config()


def _render_message(message: str, context: WorkflowContext) -> str | None:
    """Render ``message``, or return ``None`` when there's nothing to post.

    Run-level placeholders (``{devices}``, ``{device_count}``) are resolved
    first, against every device in context. If nothing ``{...}``-shaped
    remains after that, the message has no per-device placeholder -- return
    it as-is regardless of device count. Otherwise it's device-scoped: with
    no devices to resolve it against, return ``None`` (skip posting);
    with one or more devices, render once per device and join with
    newlines so every device gets its own line in the single post.
    """
    devices = list(context.devices.values())
    device_names = ", ".join(device.name for device in devices)
    aggregated = message.replace("{devices}", device_names).replace(
        "{device_count}", str(len(devices))
    )

    if "{" not in aggregated:
        return aggregated

    if not devices:
        return None

    return "\n".join(render_placeholder_template(aggregated, device) for device in devices)


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
    source_id = str(config.get("mattermost_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: mattermost_source_id is not configured")

    team_name = str(config.get("team_name") or "").strip()
    if not team_name:
        raise ValueError(f"{_STEP_ID}: team_name is not configured")

    channel_name = str(config.get("channel_name") or "").strip()
    if not channel_name:
        raise ValueError(f"{_STEP_ID}: channel_name is not configured")

    message = str(config.get("message") or defaults["message"] or "").strip()
    if not message:
        raise ValueError(f"{_STEP_ID}: message is not configured")

    rendered = _render_message(message, context)
    if rendered is None:
        logger.info(
            "%s skipped node_id=%s run_id=%s: no devices to report",
            _STEP_ID,
            node_id,
            context.run_id,
        )
        return [
            StepOutcome(
                name="success",
                context=context,
                summary="skipped: no devices to report",
            )
        ]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    credentials = resolve_mattermost_credentials(db, source_id, step_id=_STEP_ID)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    client = service_factory.get_mattermost_app_service()

    try:
        channel = await client.get_channel_by_name(credentials, team_name, channel_name)
        await client.create_post(credentials, channel["id"], rendered)
    except MattermostAPIError as exc:
        logger.warning("%s: could not post to %s/%s: %s", _STEP_ID, team_name, channel_name, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not post to {team_name}/{channel_name}: {exc}",
            )
        ]

    logger.info(
        "%s finished node_id=%s team=%s channel=%s run_id=%s",
        _STEP_ID,
        node_id,
        team_name,
        channel_name,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context,
            summary=f"posted to {team_name}/{channel_name}",
        )
    ]
