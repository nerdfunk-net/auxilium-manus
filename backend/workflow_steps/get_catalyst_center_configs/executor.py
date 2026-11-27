"""Executor for the get-catalyst-center-configs step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.controller_sources import CATALYST_CENTER
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-catalyst-center-configs"
# One request per device; keep the load on a single controller modest.
MAX_PARALLEL_REQUESTS = 5


async def _fetch_device(
    *,
    device_id: str,
    device: DeviceContext,
    credentials: CatalystCenterCredentials,
    run_id: str,
    artifact_service: ArtifactService,
) -> DeviceContext | Fail:
    """One device. A controller error is a named failure; anything else (a bug, the artifact
    store) is turned into a failed device by the runner (W8-01)."""
    command_service = service_factory.build_catalyst_center_command_service(credentials)
    try:
        running_config = await command_service.get_device_config(device_id)
    except (CatalystCenterValidationError, CatalystCenterAPIError, CatalystCenterAuthError) as exc:
        return Fail("catalyst_center_error", f"Catalyst Center request failed: {exc}", exc.failure)

    running_ref = await artifact_service.store(
        content=running_config, kind="running_config", device_id=device_id, run_id=run_id
    )
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "running_config_ref": running_ref,
            "capabilities": {*device.capabilities, Capability.RUNNING_CONFIG},
        }
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
    del config, device_sessions  # no configuration; the controller, not SSH, serves the config

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    prepared = CATALYST_CENTER.prepare_targets(context, run, step_id=_STEP_ID, node_id=node_id)
    split, credentials = prepared.split, prepared.credentials

    total = len(context.devices)
    logger.info(
        "%s started run_id=%s node_id=%s devices=%d", _STEP_ID, context.run_id, node_id, total
    )

    source_of = {
        device_id: source_id
        for source_id, devices in split.by_source.items()
        for device_id in devices
    }

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _fetch_device(
            device_id=device_id,
            device=device,
            credentials=credentials[source_of[device_id]],
            run_id=context.run_id,
            artifact_service=artifact_service,
        )

    batch = await run_per_device(
        context,
        work,
        node_id=node_id,
        step_id=_STEP_ID,
        concurrency=MAX_PARALLEL_REQUESTS,
        only=set(source_of),
    )
    succeeded = batch.ok
    failed: dict[str, DeviceContext] = {**split.rejected, **batch.failed}

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(succeeded),
        len(failed),
        context.run_id,
    )
    return build_outcomes(context, succeeded, failed)
