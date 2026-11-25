"""Executor for the get-from-user step.

Takes the target devices from a run input when the workflow run starts (via the
workflow's ``static_attributes`` run-input mechanism — see doc/WORKFLOW-STEPS.md
"Static attributes"): typed by the operator, set by a schedule, or filled by a calling
workflow's ``start-workflow`` step. It replaces a fixed canvas list (``get-from-list``)
or a live Nautobot query (``get-nautobot-devices``).

This executor has zero Nautobot dependency: it only ever reads
``run.run_inputs[device_param]`` — a plain string produced by the Run Inputs
dialog — and parses it. Whether the operator typed devices manually or picked
them from an optional Nautobot name-search suggestion in that dialog, the
value lands here in the exact same delimited-text shape (see
``workflow_steps.common.device_list.parse_device_list_text``); the executor
cannot tell the difference and never needs to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_list import (
    DEFAULT_NETWORK_DRIVER,
    device_context_from_entry,
    parse_device_list_text,
    validated_driver,
)
from workflow_steps.common.fan_out import inventory_metadata
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.get_from_user.inventory_reference import (
    inventory_device_text,
    is_inventory_reference,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)


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
    if is_inventory_reference(db, run, param_name):
        raw_value = await inventory_device_text(run, config, raw_value)

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
