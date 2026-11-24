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
import re
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.batfish_extract_facts.config import get_config
from workflow_steps.batfish_extract_facts.hsrp import mark_hsrp_error, merge_hsrp_into_facts
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-extract-facts"
_IPV4_RE = re.compile(r"\d{1,3}(\.\d{1,3}){3}")


def _node_name(device_name: str, *, short_hostname: bool) -> str:
    """Name Batfish knows this device by: the lowercased device name.

    Batfish takes a node's name from the ``hostname`` line of its config, lowercased, and never
    appends ``ip domain name``. With ``short_hostname`` (the step default) the name is cut at the
    first dot, for inventories that store the FQDN (``lab.local.zz``) while the config only says
    ``hostname LAB``.
    A bare IPv4 address is left alone: its dots are not a domain.
    """
    name = device_name.strip().lower()
    if short_hostname and not _IPV4_RE.fullmatch(name):
        return name.split(".", 1)[0] or name
    return name


def _default_nodes_filter(context: WorkflowContext, *, short_hostname: bool = False) -> str:
    """Default to just this run's devices (lowercased, comma-joined nodeSpec
    union) rather than Batfish's own "/.*/" default -- so an unconfigured
    step scopes to the workflow's own selected devices instead of every node
    in the network.

    Must be comma-joined, not "|"-joined: confirmed against a live Batfish
    coordinator that a bare (non-"/regex/"-delimited) nodeSpec containing "|"
    is parsed as one literal node name, not an alternation -- "lab|lab-2"
    matches nothing even when both "lab" and "lab-2" exist, while
    "lab,lab-2" (the documented union operator for a bare name list) matches
    both. A previous "|".join here silently produced zero-node filters for
    every multi-device run.
    """
    names = sorted(
        {
            _node_name(device.name, short_hostname=short_hostname)
            for device in context.devices.values()
            if device.name.strip()
        }
    )
    return ",".join(names) if names else "/.*/"


async def _with_hsrp_groups(
    facts: dict[str, Any], batfish: Any, snap: Any, nodes_filter: str
) -> tuple[dict[str, Any], str | None]:
    """Add ``Interfaces.<name>.HSRP_Details`` (virtual IP, priority, preempt) to the facts.

    interfaceProperties only has the group ids. A failing question must not fail the step (the
    other facts are fine), but it must not pass unnoticed either: the nodes that have HSRP groups
    get ``HSRP_Details_Error`` and the message is returned for the outcome summary.
    """
    try:
        rows = await batfish.hsrp_properties(
            snap.connection,
            batfish_network=snap.network,
            snapshot=snap.snapshot,
            nodes=nodes_filter,
        )
    except Exception as exc:
        logger.warning("%s: hsrpProperties failed, HSRP groups not added: %s", _STEP_ID, exc)
        message = f"hsrpProperties failed: {exc}"
        return mark_hsrp_error(facts, message), message
    return merge_hsrp_into_facts(facts, rows), None


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
    short_hostname = parse_bool_flag(merged_config, "use_short_hostname", default=True)
    nodes_filter = str(merged_config.get("nodes_filter") or "").strip() or _default_nodes_filter(
        context, short_hostname=short_hostname
    )

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d nodes_filter=%s network=%s snapshot=%s",
        _STEP_ID,
        log_run_id(run),
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
    facts, hsrp_error = await _with_hsrp_groups(facts, batfish, snap, nodes_filter)
    raw_node_facts = facts.get("nodes") if isinstance(facts, dict) else None
    node_facts: dict[str, Any] = raw_node_facts if isinstance(raw_node_facts, dict) else {}

    found: dict[str, DeviceContext] = {}
    missing: dict[str, DeviceContext] = {}
    for device_id, device in context.devices.items():
        node_name = _node_name(device.name, short_hostname=short_hostname)
        parsed = dict(device.parsed)
        if node_name in node_facts:
            parsed[output_key] = {"parsed": node_facts[node_name], "error": None}
            found[device_id] = device.model_copy(
                update={
                    "parsed": parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                }
            )
            continue
        message = f"no facts found for node {node_name!r} in this Batfish snapshot"
        parsed[output_key] = {"parsed": None, "error": message}
        missing[device_id] = device.model_copy(
            update={
                "parsed": parsed,
                "status": DeviceStatus.FAILED,
                "errors": [
                    *device.errors,
                    DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code="node_not_found",
                        message=message,
                    ),
                ],
            }
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
    if hsrp_error:
        metadata[f"{node_id}.{output_key}"]["warnings"] = [f"HSRP groups not added: {hsrp_error}"]

    logger.info(
        "%s finished run_id=%s nodes_extracted=%d", _STEP_ID, log_run_id(run), len(node_facts)
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": found, "metadata": metadata}),
            summary=f"Extracted facts for {len(node_facts)} node(s)"
            + (f"; HSRP groups not added: {hsrp_error}" if hsrp_error else ""),
        )
    ]
    if missing:
        # Devices without a node in the snapshot leave through "failure"; they must not
        # stay on "success" without the PARSED capability this step produces.
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": missing, "metadata": metadata}),
                summary=f"{len(missing)} device(s) not found in the snapshot",
            )
        )
    return outcomes
