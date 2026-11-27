"""Executor for the get-catalyst-center-details step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.controller_sources import CATALYST_CENTER
from workflow_steps.common.fact_entries import (
    Entry,
    FactError,
    error_entry,
    ok_entry,
    parse_name_list,
    parse_output_key_config,
)
from workflow_steps.get_catalyst_center_details.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-catalyst-center-details"
# Order of the entries on the device; ``device`` and ``software`` share one controller call.
FACTS = ("device", "software", "interfaces", "vlans", "compliance")
DEFAULT_FACTS = ("device", "interfaces")


def _parse_facts(raw: Any) -> tuple[str, ...]:
    return parse_name_list(
        raw, step_id=STEP_ID, key="facts", noun="fact", allowed=FACTS, default=DEFAULT_FACTS
    )


async def _collect(
    facts: tuple[str, ...],
    credentials: CatalystCenterCredentials,
    device_id: str,
) -> dict[str, Entry]:
    service = service_factory.build_catalyst_center_details_service(credentials)
    entries: dict[str, Entry] = {}

    record_error: FactError | None = None
    record: Any = None
    if "device" in facts or "software" in facts:
        record, record_error = await CATALYST_CENTER.capture(
            lambda: service.get_device_and_software(device_id)
        )

    for name in facts:
        if name in ("device", "software"):
            index = 0 if name == "device" else 1
            entries[name] = (
                error_entry(record_error) if record_error is not None else ok_entry(record[index])
            )
        elif name == "interfaces":
            entries[name] = await CATALYST_CENTER.fact(lambda: service.get_interfaces(device_id))
        elif name == "vlans":
            entries[name] = await CATALYST_CENTER.fact(lambda: service.get_vlans(device_id))
        elif name == "compliance":
            entries[name] = await CATALYST_CENTER.fact(lambda: service.get_compliance(device_id))
    return entries


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # facts are small JSON kept inline on the device

    facts = _parse_facts(config.get("facts"))
    output_key = parse_output_key_config(
        config.get("parsed_output_key"), step_id=STEP_ID, default=get_config()["parsed_output_key"]
    )

    async def collect(
        credentials: CatalystCenterCredentials,
        _state: Any,
        device_id: str,
        _device: DeviceContext,
    ) -> dict[str, Entry]:
        return await _collect(facts, credentials, device_id)

    return await CATALYST_CENTER.run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
    )
