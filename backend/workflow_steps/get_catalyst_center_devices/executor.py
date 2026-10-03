"""Executor for the get-catalyst-center-devices step."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session, object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters
from services.catalyst_center.device_service import CatalystCenterDeviceService
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from workflow_steps.common.device_builders import device_context_from_catalyst_center
from workflow_steps.common.fan_out import build_fan_out_metadata

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

STEP_ID = "get-catalyst-center-devices"
SOURCE_ID_KEY = "catalyst_center_source_id"
_MAX_DEVICES_CEILING = 1_000_000


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    filters: CatalystCenterDeviceFilters
    max_devices: int | None


def _parse_max_devices(raw: Any) -> int | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    value: Any = raw.strip() if isinstance(raw, str) else raw
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_DEVICES_CEILING
    ):
        raise ValueError(
            f"{STEP_ID}: max_devices must be a whole number between 1 and {_MAX_DEVICES_CEILING}"
        )
    return value


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get(SOURCE_ID_KEY) or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: {SOURCE_ID_KEY} is not configured")

    try:
        filters = CatalystCenterDeviceFilters.from_config(config.get("filters"))
    except CatalystCenterValidationError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc

    # Large inventories: an empty filter would pull every device, so it must be opted into.
    if filters.is_empty and not bool(config.get("allow_all", False)):
        raise ValueError(
            f"{STEP_ID}: no filters configured; add at least one filter or enable allow_all "
            "to select every device"
        )

    return _ParsedConfig(
        source_id=source_id,
        filters=filters,
        max_devices=_parse_max_devices(config.get("max_devices")),
    )


def _build_device_service(db: Session, source_id: str) -> CatalystCenterDeviceService:
    source_config = service_factory.build_catalyst_center_source_config_service(db)
    try:
        credentials = source_config.resolve_credentials(source_id)
    except CatalystCenterSourceNotFoundError as exc:
        raise ValueError(f"{STEP_ID}: Catalyst Center source '{source_id}' not found") from exc
    except CatalystCenterValidationError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc
    return service_factory.build_catalyst_center_device_service(credentials)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused for this step

    parsed = _parse_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")

    device_service = _build_device_service(db, parsed.source_id)

    logger.info(
        "%s started run_id=%s node_id=%s filtered=%s max_devices=%s",
        STEP_ID,
        context.run_id,
        node_id,
        not parsed.filters.is_empty,
        parsed.max_devices,
    )

    try:
        found = await device_service.search_devices(parsed.filters, max_devices=parsed.max_devices)
    except CatalystCenterValidationError as exc:
        # Includes "matched more than max_devices": a configuration problem, not an outage.
        raise ValueError(f"{STEP_ID}: {exc}") from exc
    except (CatalystCenterAPIError, CatalystCenterAuthError) as exc:
        raise RuntimeError(f"{STEP_ID}: Catalyst Center request failed: {exc}") from exc

    new_devices = {
        device.id: device_context_from_catalyst_center(device, source_id=parsed.source_id)
        for device in found
    }

    logger.info("%s finished count=%d run_id=%s", STEP_ID, len(new_devices), context.run_id)

    metadata = {
        **context.metadata,
        f"{node_id}.source_id": parsed.source_id,
        f"{node_id}.total": len(new_devices),
    }
    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)
    if fan_out_metadata is not None:
        metadata["_fan_out"] = fan_out_metadata

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
