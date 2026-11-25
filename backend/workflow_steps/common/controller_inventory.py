"""The device-inventory step of a network controller (``get-aci-devices``,
``get-catalyst-center-devices``).

Both steps read the controller's devices through a filter, wrap them as ``DeviceContext`` and
stamp the inventory metadata. They differ only in the controller: its filters, its exceptions, how
a source resolves to a service and which service method searches. ``ControllerInventory`` names
those, ``run_inventory_step`` is the one body.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from workflow_steps.common.controller_failure import controller_failure_outcomes
from workflow_steps.common.fan_out import inventory_metadata
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag

MAX_DEVICES_CEILING = 1_000_000


@dataclass(frozen=True)
class ControllerInventory:
    """What differs between two controllers' inventory steps."""

    step_id: str
    source_id_key: str
    # The step's own logger: its log lines stay attributed to the step's module.
    logger: logging.Logger
    # "APIC", "Catalyst Center": names the controller in a request failure.
    request_label: str
    validation_error: type[Exception]
    request_errors: tuple[type[Exception], ...]
    filters_from_config: Callable[[Any], Any]
    build_device_service: Callable[[Session, str], Any]
    search: Callable[[Any, Any, int | None], Awaitable[Sequence[Any]]]
    to_device: Callable[[Any, str], DeviceContext]


def parse_max_devices(raw: Any, *, step_id: str) -> int | None:
    """``max_devices``: blank means no cap, otherwise a whole number from 1 to the ceiling."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    value: Any = raw.strip() if isinstance(raw, str) else raw
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_DEVICES_CEILING
    ):
        raise ValueError(
            f"{step_id}: max_devices must be a whole number between 1 and {MAX_DEVICES_CEILING}"
        )
    return value


async def run_inventory_step(
    spec: ControllerInventory,
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    node_id: str,
) -> list[StepOutcome]:
    step_id = spec.step_id
    source_id = str(config.get(spec.source_id_key) or "").strip()
    if not source_id:
        raise ValueError(f"{step_id}: {spec.source_id_key} is not configured")

    try:
        filters = spec.filters_from_config(config.get("filters"))
    except spec.validation_error as exc:
        raise ValueError(f"{step_id}: {exc}") from exc

    # An empty filter selects every device, which a downstream step may then act on, so it must
    # be opted into.
    if filters.is_empty and not parse_bool_flag(config, "allow_all", default=False):
        raise ValueError(
            f"{step_id}: no filters configured; add at least one filter or enable allow_all "
            "to select every device"
        )
    max_devices = parse_max_devices(config.get("max_devices"), step_id=step_id)

    db = require_session(run, step_id)
    device_service = spec.build_device_service(db, source_id)

    spec.logger.info(
        "%s started run_id=%s node_id=%s filtered=%s max_devices=%s",
        step_id,
        context.run_id,
        node_id,
        not filters.is_empty,
        max_devices,
    )

    try:
        found = await spec.search(device_service, filters, max_devices)
    except spec.validation_error as exc:
        # Includes "matched more than max_devices": a configuration problem, not an outage.
        raise ValueError(f"{step_id}: {exc}") from exc
    except spec.request_errors as exc:
        return controller_failure_outcomes(
            context, exc, label=spec.request_label, step_id=step_id, logger=spec.logger
        )

    new_devices = {
        device.id: device for device in (spec.to_device(item, source_id) for item in found)
    }

    spec.logger.info("%s finished count=%d run_id=%s", step_id, len(new_devices), context.run_id)

    metadata = inventory_metadata(
        context.metadata,
        node_id,
        config.get("fan_out"),
        source_id=source_id,
        total=len(new_devices),
    ).success
    new_context = context.model_copy(
        update={"devices": {**context.devices, **new_devices}, "metadata": metadata}
    )
    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=f"found {len(new_devices)} device(s)",
        )
    ]
