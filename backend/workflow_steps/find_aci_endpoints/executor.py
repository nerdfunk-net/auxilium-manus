"""Executor for the find-aci-endpoints step: where does a device's address live in ACI?

Unlike the other ACI steps this one works on devices of *any* source (for example Nautobot): it
looks up each device's IPv4 or MAC address in the fabric's learned endpoints and records the EPG
and the leaf port (or vPC) it is attached to. Read-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.aci.credentials import AciCredentials
from services.artifacts import ArtifactService
from services.workflow_context.attribute_path import resolve_device_attribute
from workflow_steps.common.controller_sources import ACI, ACI_ERROR_CODE
from workflow_steps.common.device_outcomes import TargetSplit, mark_device_failed
from workflow_steps.common.fact_entries import Entry, collect_facts, parse_output_key_config
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.run_session import require_session
from workflow_steps.find_aci_endpoints.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "find-aci-endpoints"
SOURCE_ID_KEY = "aci_source_id"


def _address_path(config: dict[str, Any]) -> str:
    raw = config.get("address_path")
    path = get_config()["address_path"] if raw is None else str(raw).strip()
    if not path:
        raise ValueError(f"{STEP_ID}: address_path is empty")
    return path


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # the result is JSON kept inline on the device

    source_id = str(config.get(SOURCE_ID_KEY) or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: {SOURCE_ID_KEY} is not configured")
    address_path = _address_path(config)
    output_key = parse_output_key_config(
        config.get("parsed_output_key"), step_id=STEP_ID, default=get_config()["parsed_output_key"]
    )
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, STEP_ID)
    credentials = ACI.resolve_all_credentials(db, [source_id], step_id=STEP_ID)

    addresses: dict[str, str] = {}
    rejected: dict[str, DeviceContext] = {}
    for device_id, device in context.devices.items():
        # reveal_secrets=False: the value goes into an APIC query filter (and its access log), so a
        # sealed attribute must never be decrypted here; it comes back as a marker that is not an
        # address and is rejected before any request.
        address = (
            resolve_device_attribute(device, address_path, reveal_secrets=False) or ""
        ).strip()
        if address:
            addresses[device_id] = address
        else:
            rejected[device_id] = mark_device_failed(
                device,
                step_id=STEP_ID,
                node_id=node_id,
                code="no_address",
                failure=INVALID_INPUT,
                message=f"Device {device_id} has no value at '{address_path}' to look up",
            )

    async def collect(
        creds: AciCredentials, service: Any, device_id: str, _device: DeviceContext
    ) -> dict[str, Entry]:
        return {"endpoints": await ACI.fact(lambda: service.find(addresses[device_id]))}

    async def prepare(creds: AciCredentials) -> Any:
        return service_factory.build_aci_endpoint_service(creds)

    split = TargetSplit(
        by_source={source_id: {i: d for i, d in context.devices.items() if i in addresses}},
        rejected=rejected,
    )
    return await collect_facts(
        step_id=STEP_ID,
        context=context,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
        split=split,
        credentials=credentials,
        error_code=ACI_ERROR_CODE,
        prepare=prepare,
    )
