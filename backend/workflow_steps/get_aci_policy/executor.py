"""Executor for the get-aci-policy step: EPGs and contracts of each switch (read-only).

The tenant policy is read once per APIC (``prepare``); each switch then gets the EPGs deployed on
it (the same ``vlanCktEp`` read as the ``epgs`` fact of ``get-aci-details``), the L3Outs it takes
part in (with their external EPGs), the contracts they provide and consume and the definition of
those contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.aci.credentials import AciCredentials
from services.aci.policy_service import AciPolicySnapshot
from services.artifacts import ArtifactService
from workflow_steps.common.controller_sources import ACI, aci_node_of
from workflow_steps.common.fact_entries import (
    Entry,
    FactError,
    error_entry,
    ok_entry,
    parse_output_key_config,
)
from workflow_steps.get_aci_policy.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

_STEP_ID = "get-aci-policy"
ENTRY_NAMES = ("epgs", "contracts", "l3outs")

# Per-source state: the policy snapshot, or the error that stopped it.
_State = AciPolicySnapshot | FactError


async def _prepare(credentials: AciCredentials) -> _State:
    service = service_factory.build_aci_policy_service(credentials)
    snapshot, error = await ACI.capture(service.snapshot)
    return snapshot if snapshot is not None else error or FactError("APIC returned no policy")


def _error_entries(error: FactError) -> dict[str, Entry]:
    return {name: error_entry(error) for name in ENTRY_NAMES}


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # the policy is JSON kept inline on the device

    output_key = parse_output_key_config(
        config.get("parsed_output_key"), step_id=_STEP_ID, default=get_config()["parsed_output_key"]
    )

    async def collect(
        credentials: AciCredentials, state: _State, _device_id: str, device: DeviceContext
    ) -> dict[str, Entry]:
        if isinstance(state, FactError):
            return _error_entries(state)
        located = aci_node_of(device)
        if located is None:  # cannot happen after the target split
            return _error_entries(FactError("device carries no ACI node and pod id"))
        pod_id, node = located
        details = service_factory.build_aci_details_service(credentials)
        deployed, error = await ACI.capture(lambda: details.get_epgs(pod_id, node))
        if deployed is None:
            return _error_entries(error or FactError("APIC returned no EPGs"))
        epgs, contracts, l3outs = state.for_device(
            {e.epg_dn for e in deployed if e.epg_dn}, pod_id, node
        )
        return {
            "epgs": ok_entry(epgs),
            "contracts": ok_entry(contracts),
            "l3outs": ok_entry(l3outs),
        }

    return await ACI.run_fact_step(
        step_id=_STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
        prepare=_prepare,
    )
