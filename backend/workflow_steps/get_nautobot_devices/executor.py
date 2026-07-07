"""Executor for the get-nautobot-devices step."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.sources_nautobot import LogicalCondition, LogicalOperation
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.settings.source_keys import build_source_key
from workflow_steps.common.device_builders import device_context_from_nautobot

logger = logging.getLogger(__name__)


def _filter_tree_to_operations(tree: dict[str, Any]) -> list[LogicalOperation]:
    """Convert a stored FilterTree dict to LogicalOperation list."""
    if not tree or not tree.get("items"):
        return []

    def group_to_op(group: dict[str, Any]) -> LogicalOperation:
        conditions: list[LogicalCondition] = []
        nested: list[LogicalOperation] = []
        for item in group.get("items", []):
            if "items" in item:
                op = group_to_op(item)
                if item.get("negate"):
                    nested.append(
                        LogicalOperation(
                            operation_type="NOT",
                            conditions=[],
                            nested_operations=[op],
                        )
                    )
                else:
                    nested.append(op)
            else:
                conditions.append(
                    LogicalCondition(
                        field=item.get("field", ""),
                        operator=item.get("operator", ""),
                        value=item.get("value", ""),
                    )
                )
        return LogicalOperation(
            operation_type=group.get("logic", "AND"),
            conditions=conditions,
            nested_operations=nested,
        )

    op = group_to_op(tree)
    if tree.get("negate"):
        return [LogicalOperation(operation_type="NOT", conditions=[], nested_operations=[op])]
    return [op]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    source_id = config.get("nautobot_source_id", "").strip()
    device_filter = config.get("device_filter", {})

    if not source_id:
        raise ValueError("get-nautobot-devices: nautobot_source_id is not configured")

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-nautobot-devices: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(
            f"get-nautobot-devices: Nautobot source '{source_id}' not found in settings"
        )

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    if not nautobot_url or not nautobot_token:
        raise ValueError(
            f"get-nautobot-devices: Nautobot source '{source_id}' is missing url or token"
        )

    credentials = service_factory.credentials_from_connection(nautobot_url, nautobot_token)
    source_service = service_factory.build_nautobot_source_service(credentials, db)
    operations = _filter_tree_to_operations(device_filter)

    logger.info(
        "get-nautobot-devices run_id=%s source_id=%s operations=%d",
        run.id,
        source_id,
        len(operations),
    )

    devices, _ = await source_service.preview_inventory(operations)

    logger.info(
        "get-nautobot-devices returning %d devices run_id=%s",
        len(devices),
        run.id,
    )

    new_devices = {
        device.id: device_context_from_nautobot(device, source_id=source_id) for device in devices
    }
    fan_out_cfg: dict = config.get("fan_out") or {}
    fan_out_enabled = bool(fan_out_cfg.get("enabled", False))

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.source_id": source_id,
        f"{node_id}.total": len(new_devices),
    }
    if fan_out_enabled:
        metadata_update["_fan_out"] = {
            "enabled": True,
            "mode": fan_out_cfg.get("mode", "per_device"),
            "chunk_size": max(1, int(fan_out_cfg.get("chunk_size", 1))),
            "max_concurrency": max(0, int(fan_out_cfg.get("max_concurrency", 0))),
            "inventory_node_id": node_id,
        }

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )
    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=f"found {len(new_devices)} device(s)",
        )
    ]
