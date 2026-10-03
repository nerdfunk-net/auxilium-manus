"""Executor for the get-catalyst-center-configs step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

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
from workflow_steps.common.catalyst_center_targets import (
    build_outcomes,
    failed_device,
    resolve_source_credentials,
    split_targets,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

STEP_ID = "get-catalyst-center-configs"
# One request per device; keep the load on a single controller modest.
MAX_PARALLEL_REQUESTS = 5


async def _fetch_device(
    *,
    device_id: str,
    device: DeviceContext,
    credentials: CatalystCenterCredentials,
    node_id: str,
    run_id: str,
    artifact_service: ArtifactService,
    gate: asyncio.Semaphore,
) -> tuple[str, DeviceContext, bool]:
    command_service = service_factory.build_catalyst_center_command_service(credentials)
    try:
        async with gate:
            running_config = await command_service.get_device_config(device_id)
    except (CatalystCenterValidationError, CatalystCenterAPIError, CatalystCenterAuthError) as exc:
        return (
            device_id,
            failed_device(
                device,
                step_id=STEP_ID,
                node_id=node_id,
                code="catalyst_center_error",
                message=f"Catalyst Center request failed: {exc}",
            ),
            False,
        )

    running_ref = await artifact_service.store(
        content=running_config, kind="running_config", device_id=device_id, run_id=run_id
    )
    enriched = device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "running_config_ref": running_ref,
            "capabilities": {*device.capabilities, Capability.RUNNING_CONFIG},
        }
    )
    return device_id, enriched, True


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

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")

    split = split_targets(context.devices, step_id=STEP_ID, node_id=node_id)
    credentials = resolve_source_credentials(db, list(split.by_source), step_id=STEP_ID)

    total = len(context.devices)
    logger.info(
        "%s started run_id=%s node_id=%s devices=%d", STEP_ID, context.run_id, node_id, total
    )

    gate = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
    results = await asyncio.gather(
        *[
            _fetch_device(
                device_id=device_id,
                device=device,
                credentials=credentials[source_id],
                node_id=node_id,
                run_id=context.run_id,
                artifact_service=artifact_service,
                gate=gate,
            )
            for source_id, devices in split.by_source.items()
            for device_id, device in devices.items()
        ]
    )

    succeeded: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = dict(split.rejected)
    for device_id, device, ok in results:
        (succeeded if ok else failed)[device_id] = device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        STEP_ID,
        len(succeeded),
        len(failed),
        context.run_id,
    )
    return build_outcomes(context, succeeded, failed)
