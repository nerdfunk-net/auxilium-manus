"""Phase 3/4 of the fan-out parent: merge child-workflow outcomes, persist them
onto the parent run's WorkflowStepResult rows, and — when a fan-in node exists —
resume execution once on the merged (fanned-in) context.

Split out of workflow_run so the merge/persist logic has one home. The lazy,
in-function imports are deliberate (Hatchet worker import ordering / avoiding
DB-engine creation at import time) and must stay in-function.
``_finalize_fan_out_parent`` keeps its injected-dependency signature
(``SessionLocal=…, RunRepository=…, …``) unchanged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models.workflow_context import WorkflowContext

logger = logging.getLogger(__name__)


async def _finalize_fan_out_parent(
    *,
    run_id: int,
    signal: Any,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    child_results: list[dict[str, Any] | BaseException],
    SessionLocal: Any,
    RunRepository: Any,
    WorkflowRepository: Any,
    StepRunner: Any,
) -> str:
    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {run_id} not found (phase 3)")
        run, _ = run_result

        success, child_merged = _aggregate_and_persist(
            run_repo=run_repo,
            run_id=run.id,
            signal=signal,
            canvas_nodes=canvas_nodes,
            canvas_edges=canvas_edges,
            child_results=child_results,
        )

        # Phase 4: when a fan-in node exists, resume execution once on the merged
        # (fanned-in) context so git/store steps after the join run exactly once.
        if signal.join_node_id is not None:
            wf_result = wf_repo.get_by_id(run.workflow_id)
            if wf_result is None:
                raise ValueError(f"Workflow {run.workflow_id} not found (phase 4 resume)")
            wf, _ = wf_result

            # The fan-in node's parents are child-branch nodes; the inventory
            # node is included so a join wired directly to it still resolves.
            merged_outcomes: dict[str, dict[str, Any]] = {
                signal.inventory_node_id: {"success": signal.inventory_outcome}
            }
            merged_outcomes.update(child_merged)

            logger.info(
                "Fan-in resume run_id=%s join_node_id=%s",
                run_id,
                signal.join_node_id,
            )
            post_join_runner = StepRunner(db)
            try:
                join_success = await post_join_runner.resume_after_join(
                    run=run,
                    workflow=wf,
                    merged_outcomes=merged_outcomes,
                    join_node_id=signal.join_node_id,
                )
            finally:
                await post_join_runner.close_device_sessions()
            success = success and join_success

        final_status = "success" if success else "failed"
        run_repo.update_run_status(
            run,
            status=final_status,
            finished_at=datetime.now(UTC),
        )

    return final_status


def _aggregate_and_persist(
    *,
    run_repo: Any,
    run_id: int,
    signal: Any,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
    child_results: list[dict[str, Any] | BaseException],
    final: bool = True,
) -> tuple[bool, dict[str, dict[str, WorkflowContext]]]:
    """Merge child outcomes and update the parent run's WorkflowStepResult records.

    Returns ``(no_child_failure, merged_outcomes)`` where ``merged_outcomes`` maps
    each child-branch node_id → outcome_name → merged WorkflowContext (device union
    across children). The orchestrator feeds that map into ``resume_after_join`` so
    the fan-in node's inputs resolve from the fanned-in device union.

    ``final=False`` is used by Wait & Run to make finished batches inspectable
    while later batches are still gated on approval: nodes with no outcomes yet
    are left ``pending`` (they simply haven't run yet) instead of being marked
    ``skipped``, since more child_results may still arrive in a later call.
    """
    from models.workflow_context import WorkflowContext
    from services.execution.graph import child_node_ids
    from services.workflow_context.merge import merge_fan_out_contexts
    from services.workflow_context.secret_fields import redact_secrets_in_data

    # Children only produce the child branch (nodes before the fan-in node). The
    # post-join nodes are run once by the parent in resume_after_join, so they must
    # NOT be marked skipped here.
    child_ids = child_node_ids(
        signal.inventory_node_id, signal.join_node_id, canvas_nodes, canvas_edges
    )

    # Build a lookup from node_id → step result
    all_step_results = run_repo.get_step_results_for_run(run_id)
    step_result_by_node: dict[str, Any] = {sr.step_node_id: sr for sr in all_step_results}

    # Accumulate outcomes per child-branch node across all children
    per_node: dict[str, dict[str, list[WorkflowContext]]] = {nid: {} for nid in child_ids}
    # node_id -> {message, category, error_id} for the first child that reported a
    # step-level exception for that node (see StepRunner.execute_subgraph).
    node_errors: dict[str, dict[str, str]] = {}
    has_any_failure = False

    for child_result in child_results:
        if isinstance(child_result, BaseException):
            logger.error("Child workflow failed: %s", child_result)
            has_any_failure = True
            continue

        # child_result shape: {"execute_device_group": {node_id: {outcome_name: ctx_dict}}}
        task_output = child_result.get("execute_device_group", child_result)

        for node_id, err in (task_output.get("__step_errors__") or {}).items():
            node_errors.setdefault(node_id, err)

        for node_id, outcomes in task_output.items():
            if node_id == "__step_errors__" or node_id not in per_node:
                continue
            for outcome_name, ctx_dict in outcomes.items():
                ctx = WorkflowContext.model_validate(ctx_dict)
                per_node[node_id].setdefault(outcome_name, []).append(ctx)

    now = datetime.now(UTC)
    merged_outcomes: dict[str, dict[str, WorkflowContext]] = {}
    any_node_failed = False

    for node_id in child_ids:
        node_outcomes = per_node[node_id]
        step_result = step_result_by_node.get(node_id)

        if not node_outcomes:
            if final and step_result is not None:
                run_repo.update_step_result(
                    step_result,
                    status="skipped",
                    finished_at=now,
                )
            continue

        merged_output: dict[str, Any] = {}
        node_merged: dict[str, WorkflowContext] = {}
        for outcome_name, ctx_list in node_outcomes.items():
            merged_ctx = merge_fan_out_contexts(ctx_list) if len(ctx_list) > 1 else ctx_list[0]
            node_merged[outcome_name] = merged_ctx
            merged_output[outcome_name] = redact_secrets_in_data(merged_ctx.model_dump(mode="json"))
        merged_outcomes[node_id] = node_merged

        if step_result is not None:
            if has_any_failure or "failure" in node_outcomes:
                status = "partial" if "success" in node_outcomes else "failed"
            else:
                status = "success"
            if status == "failed":
                any_node_failed = True
            err = node_errors.get(node_id)
            run_repo.update_step_result(
                step_result,
                status=status,
                output={"outcomes": merged_output},
                error_message=err["message"] if err else None,
                error_category=err["category"] if err else None,
                error_id=err["error_id"] if err else None,
                started_at=now,
                finished_at=now,
            )

    return not (has_any_failure or any_node_failed), merged_outcomes
