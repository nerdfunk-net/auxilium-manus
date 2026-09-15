"""Shared engine for Batfish "property lookup" questions (Batfish Node
Properties / Batfish Interface Properties): the artifact-plus-metadata result
storage, the optional route_empty_to_devices/empty_match_mode audit filter,
and per-device enrichment on the `devices` outcome, are identical between
those two steps -- only how a row's node identity is extracted and how a
node's own fields get nested into `parsed` differs (a plain `{field: value}`
dict for nodeProperties vs. an `{"Interfaces": {...}}` wrapper for
interfaceProperties, see doc/BATFISH_INTEGRATION.md "Batfish Interface
Properties"). Captured here as `PropertyQuestionSpec` so both executors stay
thin wrappers around one engine instead of ~170 lines of duplicated logic
each.

**Extension point.** A new property-family question (e.g. a verified
bgpPeerConfiguration/ospfProcessConfiguration step) is a matter of adding one
more `PropertyQuestionSpec` -- but only once its row-identity shape has been
empirically confirmed against a live coordinator, the same way
interfaceProperties' nested `Interface` shape was confirmed here rather than
assumed (it is not a documented pybatfish invariant). See
doc/BATFISH_INTEGRATION.md "Open items" for the current state of that
verification effort.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService

logger = logging.getLogger(__name__)

EMPTY_MATCH_MODES = frozenset({"any", "all"})


def is_empty_value(value: Any) -> bool:
    """A property value counts as empty if it's unset, blank, or an empty
    collection -- e.g. Batfish's own `TACACS_Servers: []` for a node with no
    TACACS server configured."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def parse_properties_list(properties: str) -> list[str]:
    return [item.strip() for item in properties.split(",") if item.strip()]


def row_matches_empty(row: dict[str, Any], *, properties_list: list[str], match_mode: str) -> bool:
    empty_flags = [is_empty_value(row.get(prop)) for prop in properties_list]
    if match_mode == "all":
        return all(empty_flags)
    return any(empty_flags)


def validate_empty_config(
    *, step_id: str, route_empty_to_devices: bool, properties_list: list[str], match_mode: str
) -> None:
    if route_empty_to_devices and not properties_list:
        raise ValueError(
            f"{step_id}: 'properties' is required when route_empty_to_devices is enabled -- "
            "Batfish's default (unfiltered) column set has no single well-defined notion of "
            "'empty' to check against."
        )
    if match_mode not in EMPTY_MATCH_MODES:
        raise ValueError(f"{step_id}: empty_match_mode must be one of {sorted(EMPTY_MATCH_MODES)}")


@dataclass(frozen=True)
class PropertyQuestionSpec:
    """One property-family question this shared engine knows how to build
    outcomes for.

    - `question_label`: stored verbatim in the result metadata's `question`
      field (e.g. "nodeProperties").
    - `node_key`: given one row, returns the node name it belongs to (or
      None to skip it) -- the ONE identity-extraction function for this
      question; both row grouping and the identity-only DeviceContext dict
      below are derived from it, so there is nothing else that could
      disagree with it about which node a row belongs to.
    - `build_parsed_for_node`: given every row belonging to one node, returns
      that node's own `parsed[...]["parsed"]` payload -- the one place the
      node-shaped vs. interface-shaped nesting differs.
    - `row_noun`: cosmetic only, used in the `success` outcome's summary text
      (e.g. "node(s)" / "interface(s)").
    """

    question_label: str
    node_key: Callable[[dict[str, Any]], str | None]
    build_parsed_for_node: Callable[[list[dict[str, Any]]], dict[str, Any]]
    row_noun: str


def group_rows_by_node(
    rows: list[dict[str, Any]], *, node_key: Callable[[dict[str, Any]], str | None]
) -> dict[str, list[dict[str, Any]]]:
    """Group a Batfish answer's rows by node identity, dropping rows with no
    resolvable node. Shared beyond this module by
    ``workflow_steps.common.batfish_ospf_facts``, which groups four
    questions' rows the same way but merges them per node instead of
    building one ``PropertyQuestionSpec``-shaped result."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        node = node_key(row)
        if not node:
            continue
        grouped.setdefault(node, []).append(row)
    return grouped


def _enrich_devices(
    rows: list[dict[str, Any]], *, node_id: str, output_key: str, spec: PropertyQuestionSpec
) -> dict[str, DeviceContext]:
    parsed_key = f"{node_id}.{output_key}"
    rows_by_node = group_rows_by_node(rows, node_key=spec.node_key)

    enriched: dict[str, DeviceContext] = {}
    for node, node_rows in rows_by_node.items():
        device = DeviceContext(
            id=node,
            name=node,
            hostname=node,
            source="batfish",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        parsed = dict(device.parsed)
        parsed[parsed_key] = {
            "parsed": spec.build_parsed_for_node(node_rows),
            "error": None,
        }
        enriched[node] = device.model_copy(
            update={"parsed": parsed, "capabilities": device.capabilities | {Capability.PARSED}}
        )
    return enriched


async def build_property_outcomes(
    *,
    spec: PropertyQuestionSpec,
    rows: list[dict[str, Any]],
    context: WorkflowContext,
    artifact_service: ArtifactService,
    node_id: str,
    output_key: str,
    route_empty_to_devices: bool,
    properties_list: list[str],
    match_mode: str,
) -> list[StepOutcome]:
    content = json.dumps(rows, indent=2, default=str)
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
        "question": spec.question_label,
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(rows),
    }

    if route_empty_to_devices:
        devices_rows = [
            row
            for row in rows
            if row_matches_empty(row, properties_list=properties_list, match_mode=match_mode)
        ]
    else:
        devices_rows = rows
    device_nodes = _enrich_devices(devices_rows, node_id=node_id, output_key=output_key, spec=spec)

    logger.info(
        "%s finished run_id=%s node_id=%s rows=%d devices=%d route_empty_to_devices=%s",
        spec.question_label,
        context.run_id,
        node_id,
        len(rows),
        len(device_nodes),
        route_empty_to_devices,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary=f"{len(rows)} {spec.row_noun}",
        ),
        StepOutcome(
            name="devices",
            context=context.model_copy(update={"metadata": metadata, "devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        ),
    ]
