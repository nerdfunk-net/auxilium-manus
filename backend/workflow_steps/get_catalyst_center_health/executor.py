"""Executor for the get-catalyst-center-health step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_facts import (
    Entry,
    fact,
    parse_output_key_config,
    run_fact_step,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-catalyst-center-health"
DEFAULT_OUTPUT_KEY = "catalyst_health"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    output_key = parse_output_key_config(
        config.get("parsed_output_key"), step_id=STEP_ID, default=DEFAULT_OUTPUT_KEY
    )

    async def collect(
        credentials: CatalystCenterCredentials,
        _state: Any,
        device_id: str,
        _device: DeviceContext,
    ) -> dict[str, Entry]:
        service = service_factory.build_catalyst_center_health_service(credentials)
        return {"health": await fact(lambda: service.get_device_health(device_id))}

    return await run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
    )
