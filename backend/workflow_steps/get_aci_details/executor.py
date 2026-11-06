"""Executor for the get-aci-details step: per-switch facts from a Cisco ACI fabric (read-only)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.aci.credentials import AciCredentials
from services.artifacts import ArtifactService
from workflow_steps.common.aci_facts import (
    Entry,
    FactError,
    capture,
    error_entry,
    fact,
    ok_entry,
    parse_output_key_config,
    run_fact_step,
)
from workflow_steps.common.aci_targets import node_of

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-aci-details"
# Order of the entries on the device; ``device`` and ``software`` share one set of APIC reads.
FACTS = (
    "device",
    "software",
    "hardware",
    "interfaces",
    "neighbors",
    "vlans",
    "health",
    "faults",
    "routes",
    "protocols",
    "endpoints",
    "vpc",
)
DEFAULT_FACTS = ("device", "software", "interfaces")
DEFAULT_OUTPUT_KEY = "aci_details"
# Facts of one switch are read concurrently (each is a few APIC requests), but never more than
# this many at once: ``MAX_PARALLEL_DEVICES`` switches run in parallel on top of it.
MAX_PARALLEL_FACTS = 4

# fact name -> AciDetailsService method taking (pod_id, node_id); device/software are handled apart.
_FACT_METHODS = {
    "hardware": "get_hardware",
    "interfaces": "get_interfaces",
    "neighbors": "get_neighbors",
    "vlans": "get_vlans",
    "health": "get_health",
    "faults": "get_faults",
    "routes": "get_routes",
    "protocols": "get_protocols",
    "endpoints": "get_endpoints",
    "vpc": "get_vpc",
}


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
    facts: tuple[str, ...], credentials: AciCredentials, device: DeviceContext
) -> dict[str, Entry]:
    located = node_of(device)
    if located is None:  # cannot happen after the target split; fail the device, not the step
        return {name: error_entry("device carries no ACI node and pod id") for name in facts}
    pod_id, node_id = located
    service = service_factory.build_aci_details_service(credentials)
    gate = asyncio.Semaphore(MAX_PARALLEL_FACTS)

    async def device_and_software() -> dict[str, Entry]:
        # One set of APIC reads serves both facts, so it runs once whichever of them is selected.
        record, error = await capture(lambda: service.get_device_and_software(pod_id, node_id))
        wanted = [(i, name) for i, name in enumerate(("device", "software")) if name in facts]
        if record is None:
            failure = error or FactError("APIC returned no data")
            return {name: error_entry(failure) for _, name in wanted}
        return {name: ok_entry(record[index]) for index, name in wanted}

    def single(name: str) -> Callable[[], Awaitable[dict[str, Entry]]]:
        method = getattr(service, _FACT_METHODS[name])

        async def run() -> dict[str, Entry]:
            return {name: await fact(lambda: method(pod_id, node_id))}

        return run

    async def limited(job: Callable[[], Awaitable[dict[str, Entry]]]) -> dict[str, Entry]:
        async with gate:
            return await job()

    jobs = [single(name) for name in facts if name in _FACT_METHODS]
    if "device" in facts or "software" in facts:
        jobs.insert(0, device_and_software)
    merged: dict[str, Entry] = {}
    for entries in await asyncio.gather(*[limited(job) for job in jobs]):
        merged.update(entries)
    return {name: merged[name] for name in facts}


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # facts are JSON kept inline on the device

    facts = _parse_facts(config.get("facts"))
    output_key = parse_output_key_config(
        config.get("parsed_output_key"), step_id=STEP_ID, default=DEFAULT_OUTPUT_KEY
    )

    async def collect(
        credentials: AciCredentials, _state: Any, _device_id: str, device: DeviceContext
    ) -> dict[str, Entry]:
        return await _collect(facts, credentials, device)

    # Start and finish are logged once, by the shared fact driver (``collect_facts``).
    return await run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
    )
