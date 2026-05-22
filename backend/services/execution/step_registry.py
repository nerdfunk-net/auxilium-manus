"""Registry mapping step type identifiers to async executor functions.

Each executor receives:
  config        — pluginConfig dict from the canvas node (step configuration)
  parent_outputs — dict of {node_id: output_dict} for upstream steps
  run           — the WorkflowRun ORM instance

It returns a JSON-serialisable dict that becomes the step's output.

To add a new step type:
  1. Implement an async executor function below.
  2. Register it in STEP_REGISTRY under the step's kind string (hyphen-separated).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.sources_nautobot import LogicalCondition, LogicalOperation
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import build_source_key

logger = logging.getLogger(__name__)

StepExecutor = Callable[..., Awaitable[dict[str, Any]]]


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


async def _execute_get_nautobot_devices(
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
    source_service = service_factory.build_nautobot_source_service(credentials)

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
        "devices": [d.id for d in devices],
        "device_details": [d.model_dump() for d in devices],
        "source_id": source_id,
        "total": len(devices),
    }


async def _execute_get_nautobot_attributes(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    device_ids: list[str] = []
    for output in parent_outputs.values():
        if isinstance(output, dict) and "devices" in output:
            device_ids = output["devices"]
            break

    attributes = config.get("list_of_attributes", [])
    source_id = config.get("nautobot_source_id", "<not configured>")

    logger.info(
        "[mock] get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        source_id,
        len(device_ids),
        attributes,
    )

    mock_attribute_data = {
        device_id: {
            "device_id": device_id,
            "attributes": {
                "interfaces": ["GigabitEthernet0/0", "GigabitEthernet0/1"],
                "vlans": [10, 20, 100],
                "bgp_neighbors": [],
                "os_version": "15.9(3)M",
                "serial": f"SN{device_id[-3:].upper()}123",
            },
        }
        for device_id in device_ids
    }

    logger.info(
        "[mock] get-nautobot-attributes returning attributes for %d devices run_id=%s",
        len(mock_attribute_data),
        run.id,
    )

    return {
        "devices": device_ids,
        "source_id": source_id,
        "attributes_requested": attributes,
        "attribute_data": mock_attribute_data,
        "total": len(mock_attribute_data),
    }


STEP_REGISTRY: dict[str, StepExecutor] = {
    "get-nautobot-devices": _execute_get_nautobot_devices,
    "get-nautobot-attributes": _execute_get_nautobot_attributes,
}
