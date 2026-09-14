"""Executor for the batfish-extract-facts step.

Wraps Batfish's ``extract_facts`` question -- pulls the facts Batfish parsed
(hostname, NTP/TACACS/DNS servers, interfaces, BGP/OSPF settings, etc.) for a
set of nodes out of an already-initialized snapshot, with no expected values
to compare against (see batfish-validate-facts for that). See
doc/BATFISH_INTEGRATION.md "Batfish Extract Facts".

Unlike the 3 existing pure-query steps, this enriches every device in
context.devices directly: ``device.parsed[output_key] = {"parsed": <node's
facts>, "error": None}`` for a node Batfish returned, or ``{"parsed": None,
"error": "..."}`` otherwise -- the same non-fatal-per-item ``{"parsed",
"error"}`` shape run-command's TextFSM/Genie parsers use (see
doc/WORKFLOW-STEPS.md "Normalized command-output parsing"), one level
shallower since extraction isn't command-scoped. This is what lets a
downstream Jinja template read ``parsed.<output_key>.parsed.<Fact>`` per
device, in addition to the one workflow-level artifact covering every
extracted node.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import Capability, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.batfish_extract_facts.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-extract-facts"


def _default_nodes_filter(context: WorkflowContext) -> str:
    """Default to just this run's devices (lowercased, |-joined nodeSpec
    alternation) rather than Batfish's own "/.*/" default -- so an
    unconfigured step scopes to the workflow's own selected devices instead
    of every node in the network."""
    names = sorted(
        {device.name.strip().lower() for device in context.devices.values() if device.name.strip()}
    )
    return "|".join(names) if names else "/.*/"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: Batfish is reached via pybatfish, not Netmiko

    merged_config = {**get_config(), **config}
    output_key = str(merged_config.get("output_key") or "batfish_extract_facts").strip() or (
        "batfish_extract_facts"
    )
    nodes_filter = str(merged_config.get("nodes_filter") or "").strip() or _default_nodes_filter(
        context
    )

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d nodes_filter=%s network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        nodes_filter,
        snap.network,
        snap.snapshot,
    )

    facts = await batfish.extract_facts(
        snap.connection,
        batfish_network=snap.network,
        nodes=nodes_filter,
        snapshot=snap.snapshot,
    )
    raw_node_facts = facts.get("nodes") if isinstance(facts, dict) else None
    node_facts: dict[str, Any] = raw_node_facts if isinstance(raw_node_facts, dict) else {}

    devices = dict(context.devices)
    for device_id, device in devices.items():
        node_name = device.name.strip().lower()
        parsed = dict(device.parsed)
        if node_name in node_facts:
            parsed[output_key] = {"parsed": node_facts[node_name], "error": None}
            capabilities = device.capabilities | {Capability.PARSED}
        else:
            parsed[output_key] = {
                "parsed": None,
                "error": f"no facts found for node {node_name!r} in this Batfish snapshot",
            }
            capabilities = device.capabilities
        devices[device_id] = device.model_copy(
            update={"parsed": parsed, "capabilities": capabilities}
        )

    content = json.dumps(facts, indent=2, default=str)
    artifact_ref = await artifact_service.store(
        content=content,
        kind="batfish_result",
        device_id=f"batfish-{node_id}",
        run_id=context.run_id,
        media_type="application/json",
    )
    metadata = dict(context.metadata)
    metadata[f"{node_id}.{output_key}"] = {
        "kind": "batfish_result",
        "question": "extractFacts",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(node_facts),
    }

    logger.info("%s finished run_id=%s nodes_extracted=%d", _STEP_ID, run.id, len(node_facts))

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": devices, "metadata": metadata}),
            summary=f"Extracted facts for {len(node_facts)} node(s)",
        )
    ]
