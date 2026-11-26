"""Executor for the get-from-user step.

Takes the target devices from a run input when the workflow run starts (via the
workflow's ``static_attributes`` run-input mechanism — see doc/WORKFLOW-STEPS.md
"Static attributes"): typed by the operator, set by a schedule, or filled by a calling
workflow's ``start-workflow`` step. It replaces a fixed canvas list (``get-from-list``)
or a live Nautobot query (``get-nautobot-devices``).

For device text it only reads ``run.run_inputs[device_param]`` — a plain string
produced by the Run Inputs dialog — and parses it. When the run input is declared as an
inventory reference it holds an inventory id instead: the inventory is read as the run's
user (global inventories only without one) through ``services/workflow/saved_inventory.py``
and turned into the same device lines. Whether the operator typed devices manually or picked
them from an optional Nautobot name-search suggestion in that dialog, the
value lands here in the exact same delimited-text shape (see
``workflow_steps.common.device_list.parse_device_list_text``); the executor
cannot tell the difference and never needs to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.workflow.saved_inventory import (
    acting_username,
    default_nautobot_source_id,
    inventory_device_lines,
    is_inventory_reference,
)
from workflow_steps.common.device_list import (
    DEFAULT_NETWORK_DRIVER,
    device_context_from_entry,
    parse_device_list_text,
    validated_driver,
)
from workflow_steps.common.fan_out import inventory_metadata
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP = "get-from-user"


async def _inventory_device_text(
    db: Session, run: WorkflowRun, config: dict[str, Any], reference: Any
) -> str:
    """Device lines of the inventory whose id is ``reference``, read as the run's user."""
    try:
        inventory_id = int(str(reference).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{_STEP}: run parameter did not resolve to an inventory id (got {reference!r})"
        ) from exc
    configured = str(config.get("nautobot_source_id") or "").strip()
    source_id = configured or default_nautobot_source_id(db)
    if not source_id:
        raise ValueError(f"{_STEP}: no Nautobot source is configured to resolve the inventory")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP)
    service = service_factory.build_nautobot_source_service(credentials, db)
    logger.info(
        "get-from-user run_id=%s resolving inventory_id=%s source_id=%s",
        log_run_id(run),
        inventory_id,
        source_id,
    )
    username = acting_username(db, run.triggered_by_id)
    try:
        lines = await inventory_device_lines(service, inventory_id, username)
    except PermissionError as exc:
        who = (
            "the user that triggered this run"
            if username
            else "a run without a triggering user (global inventories only)"
        )
        raise ValueError(f"{_STEP}: inventory {inventory_id} is not accessible to {who}") from exc
    except ValueError as exc:
        raise ValueError(f"{_STEP}: inventory {inventory_id} cannot be used: {exc}") from exc
    return "\n".join(lines)


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

    param_name = str(config.get("device_param") or "").strip()
    if not param_name:
        raise ValueError("get-from-user: device_param is not configured")

    logger.info("get-from-user started run_id=%s param=%s", log_run_id(run), param_name)

    run_inputs = run.run_inputs or {}
    if param_name not in run_inputs:
        raise ValueError(
            f"get-from-user: run parameter {param_name!r} is not present in this run's inputs"
        )

    default_driver = (
        validated_driver(
            config.get("default_network_driver"),
            where="default_network_driver",
            step="get-from-user",
        )
        or DEFAULT_NETWORK_DRIVER
    )
    raw_value = run_inputs[param_name]
    # Without a session the inventory id would be parsed as a device name (W10-04).
    db = require_session(run, "get-from-user")
    # An inventory reference carries an inventory id; read that inventory's devices.
    if is_inventory_reference(db, run.workflow_id, param_name):
        raw_value = await _inventory_device_text(db, run, config, raw_value)

    device_entries = parse_device_list_text(raw_value, default_driver=default_driver)
    if not device_entries:
        raise ValueError("get-from-user: no devices were entered for this run")

    new_devices = {
        device.id: device
        for index, entry in enumerate(device_entries)
        for device in [
            device_context_from_entry(
                entry,
                index=index,
                node_id=node_id,
                source="run_input",
                attribute_bag_name="get_from_user",
                default_driver=default_driver,
            )
        ]
    }

    metadata = inventory_metadata(
        context.metadata,
        node_id,
        config.get("fan_out"),
        total=len(new_devices),
        devices=[device.name for device in new_devices.values()],
    )

    logger.info(
        "get-from-user returning %d devices run_id=%s",
        len(new_devices),
        log_run_id(run),
    )

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata.success,
        }
    )
    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=f"found {len(new_devices)} device(s)",
        )
    ]
