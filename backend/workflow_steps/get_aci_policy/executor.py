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
from workflow_steps.common.aci_facts import (
    Entry,
    FactError,
    capture,
    error_entry,
    ok_entry,
    parse_output_key_config,
    run_fact_step,
)
from workflow_steps.common.aci_targets import node_of

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

STEP_ID = "get-aci-policy"
DEFAULT_OUTPUT_KEY = "aci_policy"
ENTRY_NAMES = ("epgs", "contracts", "l3outs")

# Per-source state: the policy snapshot, or the error that stopped it.
_State = AciPolicySnapshot | FactError


async def _prepare(credentials: AciCredentials) -> _State:
    service = service_factory.build_aci_policy_service(credentials)
    snapshot, error = await capture(service.snapshot)
    return snapshot if snapshot is not None else error or FactError("APIC returned no policy")


def _failed(error: FactError) -> dict[str, Entry]:
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
        config.get("parsed_output_key"), step_id=STEP_ID, default=DEFAULT_OUTPUT_KEY
    )

    async def collect(
        credentials: AciCredentials, state: _State, _device_id: str, device: DeviceContext
    ) -> dict[str, Entry]:
        if isinstance(state, FactError):
            return _failed(state)
        located = node_of(device)
        if located is None:  # cannot happen after the target split
            return _failed(FactError("device carries no ACI node and pod id"))
        pod_id, node = located
        details = service_factory.build_aci_details_service(credentials)
        deployed, error = await capture(lambda: details.get_epgs(pod_id, node))
        if deployed is None:
            return _failed(error or FactError("APIC returned no EPGs"))
        epgs, contracts, l3outs = state.for_device(
            {e.epg_dn for e in deployed if e.epg_dn}, pod_id, node
        )
        return {
            "epgs": ok_entry(epgs),
            "contracts": ok_entry(contracts),
            "l3outs": ok_entry(l3outs),
        }

    return await run_fact_step(
        step_id=STEP_ID,
        context=context,
        run=run,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
        prepare=_prepare,
    )
