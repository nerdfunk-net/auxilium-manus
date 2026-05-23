"""Executor for the get-nautobot-devices step."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.sources_nautobot import DeviceInfo, LogicalCondition, LogicalOperation
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import build_source_key

logger = logging.getLogger(__name__)


def _to_device_detail(d: DeviceInfo) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "primary_ip4": {"address": d.primary_ip4} if d.primary_ip4 else None,
        "platform": {
            "name": d.platform,
            "manufacturer": d.manufacturer,
            "network_driver": d.platform_network_driver,
        }
        if (d.platform or d.platform_network_driver)
        else None,
        "serial": d.serial,
        "location": d.location,
        "role": d.role,
        "tags": d.tags,
        "device_type": d.device_type,
        "status": d.status,
    }


def _filter_tree_to_operations(tree: dict[str, Any]) -> list[LogicalOperation]:
    """Convert a stored FilterTree dict to LogicalOperation list.

    Python port of the frontend treeToOperations() from
    condition-builder/tree-to-operation.ts.
    """
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
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
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

    logger.debug("get-nautobot-devices setting.value keys=%s", list((setting.value or {}).keys()))
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

    return {
        "general": {
            "source_id": source_id,
            "total": len(devices),
        },
        "device_ids": [d.id for d in devices],
        "device_details": [_to_device_detail(d) for d in devices],
    }
