"""Executor for the undefined-and-unused step.

Wraps Batfish's ``undefinedReferences`` and ``unusedStructures`` questions --
"hygiene" checks that flag configuration references to structures that don't
exist, and structures (ACLs, route-maps, ...) that are defined but never
referenced. Routes each device to ``undefined`` and/or ``unused`` when it has
matching findings, to ``success`` when it has neither, and to ``failure``
when it couldn't be evaluated at all. Unlike ``batfish-validate-facts``'s
strict ``match``/``mismatch``/``failure`` partition, a device here can land in
both ``undefined`` and ``unused`` at once -- confirmed safe against
``StepRunner``: outcome bucketing is per-outcome-name with no invariant
limiting a device to one bucket (see doc/WORKFLOW-STEPS.md "Run and step
status"). ``success`` is exclusive of the other three: it only holds devices
with zero findings and no error.

**Row-to-device attribution.** Unlike every other typed Batfish step in this
codebase, ``undefinedReferences``/``unusedStructures`` key their rows by a
config **filename** (``File_Name`` / the filename embedded in
``Source_Lines``), not by ``Node``. Batfish resolves node<->file internally
(``loadParseVendorConfigurationAnswerElement(...).getFileMap()``, confirmed
by reading the Batfish Java source) but never exposes that map as a result
column on either question. The public equivalent is the ``fileParseStatus``
question (``File_Name``, ``Status``, ``Nodes``), which this executor calls
once per run to build a filename->node map -- this works uniformly whether
the snapshot was built in live mode (``batfish-init-snapshot`` writes
``<device_id>.cfg``) or git mode (an index-prefixed, device-agnostic
basename), sidestepping Manus's own on-disk filename convention entirely.
``fileParseStatus``'s ``Status`` also gives a real per-device signal for the
``failure`` bucket: a device whose config didn't parse cleanly gets routed to
``failure`` instead of a misleading "no findings" success.

``Status`` values are Batfish's ``ParseStatus`` enum, lowercased
(``org.batfish.datamodel.answers.ParseStatus`` -- confirmed against Batfish's
own source, and against a live coordinator that returned
``partially_unrecognized`` for a real device): ``empty``, ``failed``,
``ignored``, ``orphaned``, ``partially_unrecognized``, ``passed``,
``unexpected_packaging``, ``unknown``, ``unsupported``, ``will_not_commit``.
Only ``passed`` and ``partially_unrecognized`` are treated as "OK to
analyze" -- ``partially_unrecognized`` means Batfish still parsed and
structured the file despite skipping some unrecognized lines, so the
undefined-reference/unused-structure graph it built is still meaningful (and
is, in practice, an extremely common status for real-world configs against
whatever vendor OS version the running Batfish build doesn't fully cover
yet). Every other status means Batfish produced no reliable structure graph
for that file at all, so those route to ``failure``.
"""

from __future__ import annotations

import json
import logging
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
from services.batfish.query_helpers import (
    query_file_parse_status,
    query_undefined_references,
    query_unused_structures,
)
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.undefined_and_unused.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "undefined-and-unused"
_OUTCOME_NAMES = ("success", "undefined", "unused", "failure")
# Batfish ParseStatus values (lowercased) considered "OK to analyze" -- see
# the module docstring's ParseStatus discussion.
_PARSE_OK_STATUSES = frozenset({"passed", "partially_unrecognized"})


def _build_nodes_filter(configured: str, contributions: dict[str, str]) -> str | None:
    """A caller-supplied nodeSpec always wins (advanced override, same
    convention as every other typed Batfish step's ``nodes`` field).
    Otherwise auto-scope the query to exactly the devices this branch
    selected upstream, so findings never surface for a device the operator
    didn't choose -- returns None only when there is nothing to query."""
    configured_clean = configured.strip()
    if configured_clean:
        return configured_clean
    names = sorted(set(contributions.values()))
    if not names:
        return None
    return ",".join(names)


def _fail_device(
    device: DeviceContext, *, node_id: str, code: str, message: str
) -> DeviceContext:
    return device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [
                *device.errors,
                DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message),
            ],
        }
    )


def _with_finding(device: DeviceContext, *, key: str, rows: list[dict[str, Any]]) -> DeviceContext:
    parsed = dict(device.parsed)
    parsed[key] = {"parsed": rows, "error": None}
    return device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )


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
    output_key = str(merged_config.get("output_key") or "undefined_and_unused").strip() or (
        "undefined_and_unused"
    )

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    contributions: dict[str, str] = {}  # device_id -> node_name (lowercase)
    for device_id, device in context.devices.items():
        node_name = device.name.strip().lower()
        if not node_name:
            buckets["failure"][device_id] = _fail_device(
                device,
                node_id=node_id,
                code="missing_name",
                message="Device has no name to use as a Batfish node key",
            )
            continue
        contributions[device_id] = node_name

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        snap.network,
        snap.snapshot,
    )

    nodes_filter = _build_nodes_filter(str(merged_config.get("nodes") or ""), contributions)

    parse_rows: list[dict[str, Any]] = []
    undefined_rows: list[dict[str, Any]] = []
    unused_rows: list[dict[str, Any]] = []
    if nodes_filter is not None:
        # fileParseStatus takes no "nodes" parameter (confirmed live -- see
        # query_file_parse_status's docstring) -- it always reports every
        # file in the snapshot; irrelevant nodes are simply never looked up
        # below since we only ever index into file_to_nodes/node_status via
        # this run's own `contributions`.
        parse_rows = await query_file_parse_status(
            batfish,
            snap.connection,
            batfish_network=snap.network,
            snapshot=snap.snapshot,
        )
        undefined_rows = await query_undefined_references(
            batfish,
            snap.connection,
            batfish_network=snap.network,
            snapshot=snap.snapshot,
            nodes=nodes_filter,
        )
        unused_rows = await query_unused_structures(
            batfish,
            snap.connection,
            batfish_network=snap.network,
            snapshot=snap.snapshot,
            nodes=nodes_filter,
        )

    file_to_nodes: dict[str, list[str]] = {}
    node_status: dict[str, str] = {}
    for row in parse_rows:
        file_name = row.get("File_Name")
        if not isinstance(file_name, str):
            continue
        node_names = [str(n).strip().lower() for n in (row.get("Nodes") or [])]
        file_to_nodes[file_name] = node_names
        status = str(row.get("Status") or "").strip().lower()
        for node in node_names:
            node_status[node] = status

    undefined_by_node: dict[str, list[dict[str, Any]]] = {}
    for row in undefined_rows:
        undefined_file_name = row.get("File_Name")
        if not isinstance(undefined_file_name, str):
            continue
        for node in file_to_nodes.get(undefined_file_name, []):
            undefined_by_node.setdefault(node, []).append(row)

    unused_by_node: dict[str, list[dict[str, Any]]] = {}
    for row in unused_rows:
        source_lines = row.get("Source_Lines")
        unused_file_name = source_lines.get("filename") if isinstance(source_lines, dict) else None
        if not isinstance(unused_file_name, str):
            continue
        for node in file_to_nodes.get(unused_file_name, []):
            unused_by_node.setdefault(node, []).append(row)

    for device_id, node_name in contributions.items():
        device = context.devices[device_id]
        status = node_status.get(node_name)
        if status is None:
            buckets["failure"][device_id] = _fail_device(
                device,
                node_id=node_id,
                code="node_not_found",
                message=(
                    f"No Batfish node matching this device's name ({device.name!r}, "
                    "case-insensitive) was found in the snapshot"
                ),
            )
            continue
        if status not in _PARSE_OK_STATUSES:
            buckets["failure"][device_id] = _fail_device(
                device,
                node_id=node_id,
                code="parse_status",
                message=(
                    f"Batfish reported parse status {status!r} for this device's config "
                    "file -- undefined-reference/unused-structure results would be unreliable"
                ),
            )
            continue

        node_undefined = undefined_by_node.get(node_name, [])
        node_unused = unused_by_node.get(node_name, [])

        # Always write BOTH parsed keys (an empty list when there are no
        # findings) and always add Capability.PARSED -- the registry
        # declares produces: [parsed], and post_step_guard requires every
        # device on the outcome literally named "success" to carry it, so a
        # clean device needs the capability too, not just a device with
        # findings. This also keeps the parsed shape consistent for
        # downstream consumers regardless of which outcome a device landed
        # in (a Jinja `{{ parsed.<output_key>.undefined.parsed }}` is always
        # a list, never absent).
        enriched = _with_finding(
            device, key=f"{node_id}.{output_key}.undefined", rows=node_undefined
        )
        enriched = _with_finding(enriched, key=f"{node_id}.{output_key}.unused", rows=node_unused)

        # enriched is reused (not re-read from `device`) for whichever
        # bucket(s) apply, so a device in both `undefined` and `unused`
        # carries identical, merge-safe copies in each outcome's context --
        # see module docstring on multi-outcome membership.
        if node_undefined:
            buckets["undefined"][device_id] = enriched
        if node_unused:
            buckets["unused"][device_id] = enriched
        if not node_undefined and not node_unused:
            buckets["success"][device_id] = enriched

    content = json.dumps(
        {
            "file_parse_status": parse_rows,
            "undefined_references": undefined_rows,
            "unused_structures": unused_rows,
        },
        indent=2,
        default=str,
    )
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
        "question": "undefinedReferences+unusedStructures",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "undefined_row_count": len(undefined_rows),
        "unused_row_count": len(unused_rows),
    }

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    logger.info("%s finished run_id=%s counts=%s", _STEP_ID, run.id, counts)

    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]
