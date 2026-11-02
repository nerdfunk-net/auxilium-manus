"""Executor for the get-virtual-chassis step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nautobot_read.client import NautobotError
from nautobot_read.queries.virtual_chassis import fetch_virtual_chassis
from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.graphql_client import NautobotServiceClient
from workflow_steps.common.fan_out import build_fan_out_metadata
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.get_virtual_chassis.stack import (
    STEP_ID,
    build_stack_devices,
    matches_name,
    parse_settings,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

async def _fetch_virtual_chassis(nautobot_service: Any, credentials: Any) -> list[dict[str, Any]]:
    """Fetch every virtual chassis; the name filter is applied locally (``matches_name``).

    Not strict: as before the move into the library, a list that arrives next to a non-fatal
    GraphQL error is used (the error count is logged by the client).
    """
    client = NautobotServiceClient(nautobot_service, credentials, strict=False)
    try:
        return await fetch_virtual_chassis(client)
    except NautobotError as exc:
        raise RuntimeError(f"{STEP_ID}: Nautobot GraphQL query failed: {exc}") from exc


def _build_outcomes(
    context: WorkflowContext,
    devices: list[DeviceContext],
    *,
    fan_out_metadata: dict[str, Any] | None,
    node_id: str,
    source_id: str,
    stack_count: int,
) -> list[StepOutcome]:
    ok = {d.id: d for d in devices if d.status != DeviceStatus.FAILED}
    failed = {d.id: d for d in devices if d.status == DeviceStatus.FAILED}
    metadata = {
        **context.metadata,
        f"{node_id}.source_id": source_id,
        f"{node_id}.total": len(ok),
    }
    success_metadata = (
        {**metadata, "_fan_out": fan_out_metadata} if fan_out_metadata is not None else metadata
    )
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={"devices": {**context.devices, **ok}, "metadata": success_metadata}
            ),
            summary=f"found {stack_count} virtual chassis, {len(ok)} device(s)",
        )
    ]
    if failed:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed, "metadata": metadata}),
                summary=f"{len(failed)} device(s) without a usable primary IPv4",
            )
        )
    return outcomes


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

    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: nautobot_source_id is not configured")
    settings = parse_settings(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=STEP_ID)
    nautobot_service = service_factory.get_nautobot_app_service()

    logger.info(
        "get-virtual-chassis started run_id=%s node_id=%s source_id=%s name_match=%s "
        "name_filter=%r split_members=%s",
        run.id,
        node_id,
        source_id,
        settings.name_match,
        settings.name_filter,
        settings.split_members,
    )

    fetched = await _fetch_virtual_chassis(nautobot_service, credentials)
    chassis = [vc for vc in fetched if matches_name(str(vc.get("name") or ""), settings)]
    devices = [
        device
        for vc in chassis
        for device in build_stack_devices(vc, settings, source_id=source_id, node_id=node_id)
    ]

    outcomes = _build_outcomes(
        context,
        devices,
        fan_out_metadata=build_fan_out_metadata(config.get("fan_out"), node_id),
        node_id=node_id,
        source_id=source_id,
        stack_count=len(chassis),
    )
    failed_count = sum(1 for d in devices if d.status == DeviceStatus.FAILED)
    logger.info(
        "get-virtual-chassis finished virtual_chassis=%d devices=%d failed=%d run_id=%s",
        len(chassis),
        len(devices) - failed_count,
        failed_count,
        run.id,
    )
    return outcomes
