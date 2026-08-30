"""Executor for the get-nautobot-devices step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.sources_nautobot import LogicalCondition, LogicalOperation
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_builders import device_context_from_nautobot
from workflow_steps.common.fan_out import build_fan_out_metadata
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

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
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    source_id = config.get("nautobot_source_id", "").strip()
    device_filter = config.get("device_filter", {})
    inventory_type = config.get("inventory_type", "filter")
    device_ids = config.get("device_ids") or []

    if not source_id:
        raise ValueError("get-nautobot-devices: nautobot_source_id is not configured")

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-nautobot-devices: WorkflowRun has no active DB session")

    credentials = resolve_nautobot_credentials(db, source_id, step_id="get-nautobot-devices")
    source_service = service_factory.build_nautobot_source_service(credentials, db)

    if inventory_type == "static":
        logger.info(
            "get-nautobot-devices run_id=%s source_id=%s inventory_type=static device_ids=%d",
            run.id,
            source_id,
            len(device_ids),
        )
        devices = await source_service.resolve_devices_by_ids(device_ids)
    else:
        operations = _filter_tree_to_operations(device_filter)
        logger.info(
            "get-nautobot-devices run_id=%s source_id=%s inventory_type=filter operations=%d",
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
    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.source_id": source_id,
        f"{node_id}.total": len(new_devices),
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

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
