"""Executor for the get-catalyst-center-devices step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

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
from workflow_steps.common.controller_inventory import ControllerInventory, run_inventory_step
from workflow_steps.common.controller_sources import CATALYST_CENTER
from workflow_steps.common.device_builders import device_context_from_catalyst_center

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-catalyst-center-devices"
SOURCE_ID_KEY = "catalyst_center_source_id"


def _build_device_service(db: Session, source_id: str) -> CatalystCenterDeviceService:
    credentials = CATALYST_CENTER.resolve_credentials(db, source_id, step_id=_STEP_ID)
    return service_factory.build_catalyst_center_device_service(credentials)


async def _search(
    service: CatalystCenterDeviceService, filters: Any, max_devices: int | None
) -> Any:
    return await service.search_devices(filters, max_devices=max_devices)


_SPEC = ControllerInventory(
    step_id=_STEP_ID,
    source_id_key=SOURCE_ID_KEY,
    logger=logger,
    request_label="Catalyst Center",
    validation_error=CatalystCenterValidationError,
    request_errors=(CatalystCenterAPIError, CatalystCenterAuthError),
    filters_from_config=CatalystCenterDeviceFilters.from_config,
    build_device_service=_build_device_service,
    search=_search,
    to_device=lambda device, source_id: device_context_from_catalyst_center(
        device, source_id=source_id
    ),
)


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
    return await run_inventory_step(_SPEC, config=config, context=context, run=run, node_id=node_id)
