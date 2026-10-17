"""Executor for the get-catalyst-center-topology step."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.catalyst_center_facts import CatalystCenterTopology
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_facts import (
    Entry,
    FactError,
    capture,
    error_entry,
    ok_entry,
    parse_output_key_config,
    run_fact_step,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-catalyst-center-topology"
TOPOLOGIES = ("physical", "l3_ospf", "l3_isis", "l3_eigrp", "l3_static")
DEFAULT_TOPOLOGIES = ("physical",)
DEFAULT_OUTPUT_KEY = "catalyst_topology"

# name -> topology, or the error text when the controller call failed
_Fetched = dict[str, CatalystCenterTopology | FactError]


def _parse_topologies(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_TOPOLOGIES
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{STEP_ID}: topologies must be a list of topology names")
    unknown = sorted({item for item in raw if item not in TOPOLOGIES})
    if unknown:
        raise ValueError(f"{STEP_ID}: unknown topology {unknown}; choose from {list(TOPOLOGIES)}")
    if not raw:
        raise ValueError(f"{STEP_ID}: select at least one topology")
    return tuple(name for name in TOPOLOGIES if name in raw)


async def _fetch_topologies(
    topologies: tuple[str, ...], credentials: CatalystCenterCredentials
) -> _Fetched:
    """The graphs are controller-wide, so fetch each once per controller, not per device."""
    service = service_factory.build_catalyst_center_topology_service(credentials)

    async def fetch(name: str) -> tuple[str, CatalystCenterTopology | FactError]:
        if name == "physical":
            graph, error = await capture(service.get_physical_topology)
        else:
            protocol = name.removeprefix("l3_")
            graph, error = await capture(lambda: service.get_l3_topology(protocol))
        if graph is None:
            return name, error or FactError("Catalyst Center returned no topology")
        return name, graph

    return dict(await asyncio.gather(*[fetch(name) for name in topologies]))


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

    topologies = _parse_topologies(config.get("topologies"))
    output_key = parse_output_key_config(
        config.get("parsed_output_key"), step_id=STEP_ID, default=DEFAULT_OUTPUT_KEY
    )

    async def prepare(credentials: CatalystCenterCredentials) -> _Fetched:
        return await _fetch_topologies(topologies, credentials)

    async def collect(
        _credentials: CatalystCenterCredentials,
        fetched: _Fetched,
        device_id: str,
        _device: DeviceContext,
    ) -> dict[str, Entry]:
        return {
            name: error_entry(graph)
            if isinstance(graph, FactError)
            else ok_entry(graph.for_device(device_id))
            for name, graph in fetched.items()
        }

    return await run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
        prepare=prepare,
    )
