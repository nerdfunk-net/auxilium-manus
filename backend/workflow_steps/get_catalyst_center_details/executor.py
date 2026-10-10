"""Executor for the get-catalyst-center-details step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_facts import (
    Entry,
    FactError,
    capture,
    error_entry,
    fact,
    ok_entry,
    parse_output_key_config,
    run_fact_step,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-catalyst-center-details"
# Order of the entries on the device; ``device`` and ``software`` share one controller call.
FACTS = ("device", "software", "interfaces", "vlans", "compliance")
DEFAULT_FACTS = ("device", "interfaces")
DEFAULT_OUTPUT_KEY = "catalyst_details"


def _parse_facts(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_FACTS
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{STEP_ID}: facts must be a list of fact names")
    unknown = sorted({item for item in raw if item not in FACTS})
    if unknown:
        raise ValueError(f"{STEP_ID}: unknown fact(s) {unknown}; choose from {list(FACTS)}")
    if not raw:
        raise ValueError(f"{STEP_ID}: select at least one fact")
    return tuple(name for name in FACTS if name in raw)


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
        record, record_error = await capture(lambda: service.get_device_and_software(device_id))

    for name in facts:
        if name in ("device", "software"):
            index = 0 if name == "device" else 1
            entries[name] = (
                error_entry(record_error) if record_error is not None else ok_entry(record[index])
            )
        elif name == "interfaces":
            entries[name] = await fact(lambda: service.get_interfaces(device_id))
        elif name == "vlans":
            entries[name] = await fact(lambda: service.get_vlans(device_id))
        elif name == "compliance":
            entries[name] = await fact(lambda: service.get_compliance(device_id))
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
        config.get("parsed_output_key"), step_id=STEP_ID, default=DEFAULT_OUTPUT_KEY
    )

    async def collect(
        credentials: CatalystCenterCredentials,
        _state: Any,
        device_id: str,
        _device: DeviceContext,
    ) -> dict[str, Entry]:
        return await _collect(facts, credentials, device_id)

    return await run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
    )
