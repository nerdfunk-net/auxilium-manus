"""Executor for the workflow-log debugging step."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_path import (
    DEBUG_LOGS_METADATA_SUFFIX,
    resolve_device_value,
)
from workflow_steps.workflow_log.config import get_config

logger = logging.getLogger(__name__)


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_attribute_paths(config: dict[str, Any]) -> list[str]:
    raw_paths = config.get("attribute_paths")
    if raw_paths is None:
        raw_paths = _default_config()["attribute_paths"]
    if isinstance(raw_paths, str):
        stripped = raw_paths.strip()
        if not stripped:
            paths: list[str] = []
        else:
            try:
                raw_paths = json.loads(stripped)
            except json.JSONDecodeError:
                raw_paths = [item.strip() for item in stripped.splitlines() if item.strip()]
    if not isinstance(raw_paths, list):
        raise ValueError("workflow-log: attribute_paths must be a list of strings")

    paths = [str(path).strip() for path in raw_paths if str(path).strip()]
    if not paths:
        raise ValueError("workflow-log: at least one attribute_path is required")
    return paths


def _serialize_log_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dict, list)):
        return value
    return str(value)


def _build_device_log_entry(
    *,
    device_id: str,
    device_name: str,
    attribute_paths: list[str],
    context: WorkflowContext,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path in attribute_paths:
        device = context.devices[device_id]
        values[path] = _serialize_log_value(
            resolve_device_value(device, path, run_id=context.run_id)
        )
    return {
        "device_id": device_id,
        "device_name": device_name,
        "values": values,
    }


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del run, artifact_service

    attribute_paths = _parse_attribute_paths(config)
    message = str(config.get("message") or _default_config()["message"] or "").strip()
    logged_at = datetime.now(timezone.utc).isoformat()

    device_logs: dict[str, dict[str, Any]] = {}
    for device_id, device in context.devices.items():
        entry = _build_device_log_entry(
            device_id=device_id,
            device_name=device.name,
            attribute_paths=attribute_paths,
            context=context,
        )
        device_logs[device_id] = entry
        logger.info(
            "workflow-log node_id=%s device_id=%s message=%r values=%s",
            node_id,
            device_id,
            message,
            entry["values"],
        )

    debug_logs = {
        "message": message,
        "logged_at": logged_at,
        "attribute_paths": attribute_paths,
        "device_count": len(device_logs),
        "devices": device_logs,
    }

    metadata = {
        **context.metadata,
        f"{node_id}{DEBUG_LOGS_METADATA_SUFFIX}": debug_logs,
    }

    logger.info(
        "workflow-log node_id=%s devices=%d paths=%s",
        node_id,
        len(device_logs),
        attribute_paths,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
        )
    ]
