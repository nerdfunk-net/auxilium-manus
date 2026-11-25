"""Generic engine behind the "combined facts" Batfish steps (Get OSPF Facts, Get BGP Facts):
make up to N Batfish calls, store one artifact per enabled question and merge all enabled
questions' rows into one payload per device.

``CombinedQuestionSpec`` and the per-node merge live in ``services.batfish.facts_specs`` (the
ad-hoc preview in ``services.batfish.preview_service`` builds on the same merge). The two steps
differ only in their spec table and in which query function answers which question, so
``run_combined_facts_step`` owns the whole body and each executor is a table plus one call.

``rows_by_question`` carries only the ENABLED questions of a run: a question the step config
disabled is absent from both the stored artifacts and the merged per-device payload, never
present with a null/empty value.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.facts_specs import CombinedQuestionSpec, merge_facts_by_node
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.batfish_results import batfish_node_device, store_batfish_result
from workflow_steps.common.fact_entries import parse_output_key_config
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

__all__ = ["QueryFn", "build_combined_facts_outcomes", "run_combined_facts_step"]

logger = logging.getLogger(__name__)

# (batfish, connection, *, batfish_network, snapshot, nodes) -> rows
QueryFn = Callable[..., Awaitable[list[dict[str, Any]]]]


async def build_combined_facts_outcomes(
    *,
    step_id: str,
    specs: dict[str, CombinedQuestionSpec],
    context: WorkflowContext,
    artifact_service: ArtifactService,
    node_id: str,
    output_key: str,
    rows_by_question: dict[str, list[dict[str, Any]]],
) -> list[StepOutcome]:
    metadata = dict(context.metadata)
    summary_parts: list[str] = []

    for key, rows in rows_by_question.items():
        spec = specs[key]
        metadata[f"{node_id}.{output_key}.{key}"] = await store_batfish_result(
            artifact_service,
            rows,
            context=context,
            node_id=node_id,
            question=spec.question_label,
            row_count=len(rows),
        )
        summary_parts.append(f"{len(rows)} {spec.row_noun}")

    payloads_by_node = merge_facts_by_node(specs, rows_by_question)
    device_nodes: dict[str, DeviceContext] = {}
    for node, parsed_payload in payloads_by_node.items():
        device_nodes[node] = batfish_node_device(node, parsed=True).model_copy(
            update={
                "parsed": {node_id: {output_key: {"parsed": parsed_payload, "error": None}}}
            }
        )

    logger.info(
        "%s finished run_id=%s node_id=%s questions=%s devices=%d",
        step_id,
        context.run_id,
        node_id,
        sorted(rows_by_question),
        len(device_nodes),
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
            summary="; ".join(summary_parts) if summary_parts else "0 rows",
        ),
        StepOutcome(
            name="devices",
            context=context.model_copy(update={"metadata": metadata, "devices": device_nodes}),
            summary=f"{len(device_nodes)} device(s)",
        ),
    ]


async def run_combined_facts_step(
    *,
    step_id: str,
    specs: dict[str, CombinedQuestionSpec],
    queries: Mapping[str, QueryFn],
    default_output_key: str,
    default_config: dict[str, Any],
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    """The whole body of a combined-facts step.

    Each question ``key`` of ``specs`` is switched by the config toggle ``include_<key>`` (default
    on) and answered by ``queries[key]``.
    """
    merged_config = {**default_config, **config}
    output_key = parse_output_key_config(
        merged_config.get("output_key"),
        step_id=step_id,
        default=default_output_key,
        key_name="output_key",
    )
    enabled_keys = [
        key
        for key in specs
        if parse_bool_flag(merged_config, f"include_{key}", default=True, step_id=step_id)
    ]
    if not enabled_keys:
        toggles = "/".join(f"include_{key}" for key in specs)
        raise ValueError(f"{step_id}: at least one of {toggles} must be enabled")

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s network=%s snapshot=%s questions=%s",
        step_id,
        log_run_id(run),
        node_id,
        snap.network,
        snap.snapshot,
        enabled_keys,
    )

    nodes = merged_config.get("nodes")
    rows_by_question: dict[str, list[dict[str, Any]]] = {}
    for key in enabled_keys:
        rows_by_question[key] = await queries[key](
            batfish,
            snap.connection,
            batfish_network=snap.network,
            snapshot=snap.snapshot,
            nodes=nodes,
        )

    return await build_combined_facts_outcomes(
        step_id=step_id,
        specs=specs,
        context=context,
        artifact_service=artifact_service,
        node_id=node_id,
        output_key=output_key,
        rows_by_question=rows_by_question,
    )
