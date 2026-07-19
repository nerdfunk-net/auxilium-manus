"""Executor for the workflow-log debugging step."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_path import (
    DEBUG_LOGS_METADATA_SUFFIX,
    resolve_device_attribute,
)
from workflow_steps.workflow_log.config import get_config

logger = logging.getLogger(__name__)

_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z0-9_.]+)\}")


def _default_config() -> dict[str, Any]:
    return get_config()


def render_message_template(template: str, device: DeviceContext) -> str:
    """Replace ``{path.to.value}`` placeholders with the device's resolved
    attribute values. A path that resolves to nothing renders as an empty
    string rather than failing the step."""

    def _replace(match: re.Match[str]) -> str:
        # workflow-log writes into INFO logs and persisted step metadata, so
        # secret-valued paths must never be rehydrated here — reveal_secrets=False
        # returns REDACTED_PLACEHOLDER instead of the cleartext.
        value = resolve_device_attribute(device, match.group(1), reveal_secrets=False)
        return value if value is not None else ""

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del run, artifact_service

    message = str(config.get("message") or _default_config()["message"] or "").strip()
    if not message:
        raise ValueError("workflow-log: message is required")

    logged_at = datetime.now(timezone.utc).isoformat()

    device_logs: dict[str, dict[str, Any]] = {}
    for device_id, device in context.devices.items():
        rendered = render_message_template(message, device)
        device_logs[device_id] = {
            "device_id": device_id,
            "device_name": device.name,
            "message": rendered,
        }
        logger.info(
            "workflow-log node_id=%s device_id=%s message=%r",
            node_id,
            device_id,
            rendered,
        )

    debug_logs = {
        "message": message,
        "logged_at": logged_at,
        "device_count": len(device_logs),
        "devices": device_logs,
    }

    metadata = {
        **context.metadata,
        f"{node_id}{DEBUG_LOGS_METADATA_SUFFIX}": debug_logs,
    }

    logger.info("workflow-log node_id=%s devices=%d", node_id, len(device_logs))

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"logged {len(device_logs)} device(s): {message!r}",
        )
    ]
