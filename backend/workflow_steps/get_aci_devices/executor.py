"""Executor for the get-aci-devices step: leaf and spine switches of a Cisco ACI fabric."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.aci.device_filters import AciDeviceFilters
from services.aci.device_service import AciDeviceService
from services.artifacts import ArtifactService
from workflow_steps.common.controller_inventory import ControllerInventory, run_inventory_step
from workflow_steps.common.controller_sources import ACI
from workflow_steps.common.device_builders import device_context_from_aci

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-aci-devices"
SOURCE_ID_KEY = "aci_source_id"


def _build_device_service(db: Session, source_id: str) -> AciDeviceService:
    credentials = ACI.resolve_credentials(db, source_id, step_id=_STEP_ID)
    return service_factory.build_aci_device_service(credentials)


async def _search(service: AciDeviceService, filters: Any, max_devices: int | None) -> Any:
    return await service.search(filters, max_devices=max_devices)


_SPEC = ControllerInventory(
    step_id=_STEP_ID,
    source_id_key=SOURCE_ID_KEY,
    logger=logger,
    request_label="APIC",
    validation_error=AciValidationError,
    request_errors=(AciAPIError, AciAuthError),
    filters_from_config=AciDeviceFilters.from_config,
    build_device_service=_build_device_service,
    search=_search,
    to_device=lambda device, source_id: device_context_from_aci(device, source_id=source_id),
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
