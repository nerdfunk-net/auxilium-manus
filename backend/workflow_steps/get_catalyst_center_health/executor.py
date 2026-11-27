"""Executor for the get-catalyst-center-health step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.controller_sources import CATALYST_CENTER
from workflow_steps.common.fact_entries import Entry, parse_output_key_config
from workflow_steps.get_catalyst_center_health.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-catalyst-center-health"


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
        config.get("parsed_output_key"), step_id=STEP_ID, default=get_config()["parsed_output_key"]
    )

    async def collect(
        credentials: CatalystCenterCredentials,
        _state: Any,
        device_id: str,
        _device: DeviceContext,
    ) -> dict[str, Entry]:
        service = service_factory.build_catalyst_center_health_service(credentials)
        return {"health": await CATALYST_CENTER.fact(lambda: service.get_device_health(device_id))}

    return await CATALYST_CENTER.run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
    )
