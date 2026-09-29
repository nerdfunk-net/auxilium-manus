"""Executor for the get-nautobot-devices step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.sources_nautobot import DeviceInfo, LogicalCondition, LogicalOperation
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_builders import device_context_from_nautobot
from workflow_steps.common.fan_out import build_fan_out_metadata
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.run_param_reference import resolve_config_reference

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


def _acting_username(db: Any, user_id: int | None) -> str | None:
    """Username of the user that triggered this run — used to RBAC-scope a
    run-parameter inventory lookup to global + that user's private inventories.
    ``None`` for a system-triggered run with no user (only global inventories
    then resolve, via the persistence layer's access check)."""
    if user_id is None:
        return None
    from repositories.user_repository import UserRepository

    user = UserRepository(db).get_by_id(user_id)
    return user.username if user else None


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


async def _resolve_saved_inventory(
    source_service: Any,
    *,
    db: Any,
    run: WorkflowRun,
    config: dict[str, Any],
    reference: str,
    from_run_param: bool,
    source_id: str,
) -> list[DeviceInfo]:
    """Resolve a saved inventory to devices, RBAC-scoped to the triggering user."""
    origin = "run parameter" if from_run_param else "selected inventory"
    try:
        inventory_id = int(reference)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"get-nautobot-devices: {origin} did not resolve to an inventory id (got {reference!r})"
        ) from exc

    acting_username = _acting_username(db, run.triggered_by_id)
    logger.info(
        "get-nautobot-devices run_id=%s source_id=%s inventory_source=%s "
        "inventory_id=%s acting_user=%s",
        run.id,
        source_id,
        "run_param" if from_run_param else "fixed",
        inventory_id,
        acting_username,
    )
    try:
        return await source_service.resolve_saved_inventory_devices_by_id(
            inventory_id, acting_username
        )
    except PermissionError as exc:
        raise ValueError(
            f"get-nautobot-devices: inventory {inventory_id} is not accessible to the "
            f"user that triggered this run"
        ) from exc
    except ValueError as exc:
        # Deleted / inactive / unreadable. Fail loudly: silently falling back to
        # the step's old copy would run against devices nobody chose any more.
        name = str(config.get("inventory_name") or "").strip()
        label = f"{inventory_id} ({name!r})" if name and not from_run_param else str(inventory_id)
        hint = "" if from_run_param else " Select an inventory again in the step."
        raise ValueError(
            f"get-nautobot-devices: saved inventory {label} cannot be used: {exc}.{hint}"
        ) from exc


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

    from_run_param = str(config.get("inventory_source") or "fixed").strip() == "run_param"
    # The inventory id comes either from a run parameter or from the id selected in
    # the workflow builder (`inventory_id`); the helper raises if a run parameter
    # is selected but unset, instead of falling back to a stale literal.
    inventory_reference = resolve_config_reference(
        config,
        source_key="inventory_source",
        param_key="inventory_param",
        literal_key="inventory_id",
        run_inputs=run.run_inputs,
    )

    if from_run_param or inventory_reference:
        # A saved inventory is always resolved live — through this one path for both
        # ways of naming it — so editing the inventory changes what the next run
        # targets. The step's own device_filter / device_ids copy is not consulted.
        devices = await _resolve_saved_inventory(
            source_service,
            db=db,
            run=run,
            config=config,
            reference=inventory_reference,
            from_run_param=from_run_param,
            source_id=source_id,
        )
    elif inventory_type == "static":
        logger.info(
            "get-nautobot-devices run_id=%s source_id=%s inventory_type=static device_ids=%d",
            run.id,
            source_id,
            len(device_ids),
        )
        devices = await source_service.resolve_devices_by_ids(device_ids)
    else:
        # Ad-hoc selection with no saved inventory (imported / AI-written workflows):
        # the filter stored in the step is the definition.
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
