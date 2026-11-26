"""Shared engine for Batfish "property lookup" questions (Batfish Node
Properties / Batfish Interface Properties): the artifact-plus-metadata result
storage, the optional route_empty_to_devices/empty_match_mode audit filter,
and per-device enrichment on the `devices` outcome, are identical between
those two steps -- only how a row's node identity is extracted and how a
node's own fields get nested into `parsed` differs (a plain `{field: value}`
dict for nodeProperties vs. an `{"Interfaces": {...}}` wrapper for
interfaceProperties, see doc/BATFISH_INTEGRATION.md "Batfish Interface
Properties"). Captured as `PropertyQuestionSpec` so both executors stay thin
wrappers around one engine instead of ~170 lines of duplicated logic each.

`PropertyQuestionSpec` and `group_rows_by_node` themselves now live in
`services.batfish.facts_specs` (re-exported here for backward-compatible
imports) -- moved there so `services.batfish.preview_service` can build the
ad-hoc "Batfish Node/Interface Properties" preview from the exact same
grouping logic, without a service importing from `workflow_steps` (see that
module's docstring).

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

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import Capability, DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.facts_specs import (
    PropertyQuestionSpec,
    facts_by_node_for_property,
)
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_results import batfish_node_device, store_batfish_result
from workflow_steps.common.fact_entries import parse_output_key_config
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

__all__ = [
    "EMPTY_MATCH_MODES",
    "run_property_step",
    "assert_requested_columns_present",
    "build_property_outcomes",
    "parse_properties_list",
    "validate_empty_config",
]

logger = logging.getLogger(__name__)

EMPTY_MATCH_MODES = frozenset({"any", "all"})


def _is_empty_value(value: Any) -> bool:
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


def _row_matches_empty(row: dict[str, Any], *, properties_list: list[str], match_mode: str) -> bool:
    empty_flags = [_is_empty_value(row.get(prop)) for prop in properties_list]
    if match_mode == "all":
        return all(empty_flags)
    return any(empty_flags)


def assert_requested_columns_present(
    *, step_id: str, rows: list[dict[str, Any]], properties_list: list[str]
) -> None:
    """A typo'd property name must not send every node to the "empty" handle.

    When Batfish answered with rows but none of them has any of the requested properties as a
    column, the request matched nothing: fail the step instead of reading "no column" as "empty".
    """
    if not properties_list or not rows:
        return
    columns: set[str] = set()
    for row in rows:
        columns.update(row)
    if not any(prop in columns for prop in properties_list):
        raise ValueError(
            f"{step_id}: none of the requested properties exist in the Batfish answer: "
            f"{', '.join(properties_list)}"
        )


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


def _enrich_devices(
    rows: list[dict[str, Any]], *, node_id: str, output_key: str, spec: PropertyQuestionSpec
) -> dict[str, DeviceContext]:
    payloads_by_node = facts_by_node_for_property(spec, rows)

    enriched: dict[str, DeviceContext] = {}
    for node, payload in payloads_by_node.items():
        device = batfish_node_device(node)
        parsed = set_node_result(
            device.parsed, node_id, output_key, {"parsed": payload, "error": None}
        )
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
    metadata = dict(context.metadata)
    metadata[f"{node_id}.{output_key}"] = await store_batfish_result(
        artifact_service,
        rows,
        context=context,
        node_id=node_id,
        question=spec.question_label,
        row_count=len(rows),
    )

    if route_empty_to_devices:
        devices_rows = [
            row
            for row in rows
            if _row_matches_empty(row, properties_list=properties_list, match_mode=match_mode)
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


async def run_property_step(
    *,
    step_id: str,
    spec: PropertyQuestionSpec,
    query: Callable[..., Awaitable[list[dict[str, Any]]]],
    extra_filters: tuple[str, ...] = (),
    default_output_key: str,
    default_config: dict[str, Any],
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    """The whole body of a property step (Batfish Node / Interface Properties).

    ``query`` is called with ``nodes`` and ``properties`` plus one keyword per name in
    ``extra_filters``, each read from the config under the same name.
    """
    merged_config = {**default_config, **config}
    output_key = parse_output_key_config(
        merged_config.get("output_key"),
        step_id=step_id,
        default=default_output_key,
        key_name="output_key",
    )
    properties_list = parse_properties_list(str(merged_config.get("properties") or ""))
    route_empty_to_devices = parse_bool_flag(merged_config, "route_empty_to_devices")
    match_mode = str(merged_config.get("empty_match_mode") or "any").strip().lower()
    validate_empty_config(
        step_id=step_id,
        route_empty_to_devices=route_empty_to_devices,
        properties_list=properties_list,
        match_mode=match_mode,
    )

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s",
        step_id,
        log_run_id(run),
        node_id,
        snap.network,
        snap.snapshot,
    )

    rows = await query(
        batfish,
        snap.connection,
        batfish_network=snap.network,
        snapshot=snap.snapshot,
        nodes=merged_config.get("nodes"),
        properties=merged_config.get("properties"),
        **{name: merged_config.get(name) for name in extra_filters},
    )

    assert_requested_columns_present(step_id=step_id, rows=rows, properties_list=properties_list)

    return await build_property_outcomes(
        spec=spec,
        rows=rows,
        context=context,
        artifact_service=artifact_service,
        node_id=node_id,
        output_key=output_key,
        route_empty_to_devices=route_empty_to_devices,
        properties_list=properties_list,
        match_mode=match_mode,
    )
