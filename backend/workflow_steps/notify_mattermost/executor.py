"""Executor for the notify-mattermost step.

Posts one message per step execution to a Mattermost channel, resolved via a
configured Mattermost source, team name, and channel name. ``message``
supports three run-level placeholders that don't come from any single device
-- ``{devices}`` (comma-joined device names), ``{device_count}`` and
``{run_summary}`` (see ``common/run_message_template.py``) -- plus
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

import service_factory
from core.models.runs import WorkflowRun
from models.failure import failure_from_exception
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.mattermost.common.exceptions import MattermostAPIError
from workflow_steps.common.failure_records import TRANSPORT_FAILED
from workflow_steps.common.mattermost_source import resolve_mattermost_credentials
from workflow_steps.common.notification_target import parse_mattermost_target
from workflow_steps.common.run_message_template import render_for_all_devices
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import require_text
from workflow_steps.notify_mattermost.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "notify-mattermost"
# Mattermost rejects a post above 16 383 characters; a long device list is cut, not failed.
MATTERMOST_MAX_POST = 15_000


def _truncate_post(text: str) -> str:
    if len(text) <= MATTERMOST_MAX_POST:
        return text
    return f"{text[:MATTERMOST_MAX_POST]}… ({len(text) - MATTERMOST_MAX_POST} more characters)"


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

    source_id, team_name, channel_name = parse_mattermost_target(config, step_id=_STEP_ID)
    message = require_text(config, "message", step_id=_STEP_ID, default=get_config()["message"])

    rendered = render_for_all_devices(message, context)
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

    db = require_session(run, _STEP_ID)

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
        await client.create_post(credentials, channel["id"], _truncate_post(rendered))
    except MattermostAPIError as exc:
        logger.warning("%s: could not post to %s/%s: %s", _STEP_ID, team_name, channel_name, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not post to {team_name}/{channel_name}: {exc}",
                failure=failure_from_exception(exc) or TRANSPORT_FAILED,
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
