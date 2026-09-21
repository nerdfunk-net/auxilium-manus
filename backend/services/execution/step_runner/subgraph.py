"""Fan-out child execution: run only the allowed downstream subgraph, without
writing WorkflowStepResult rows (the parent aggregates and persists). Split
out of the StepRunner class because it is a self-contained second walk with
its own bookkeeping; it reuses the runner's per-node primitives via an
explicit ``runner`` handle rather than ``self``.

Like ``StepRunner.execute_all``/``resume_after_join``, independent siblings in
this subgraph run concurrently (topological generations, see
``services.execution.graph.topological_generations``). This walk needs no
``asyncio.Lock`` around DB writes the way those two do — it writes zero
``WorkflowStepResult`` rows during the walk at all; the parent aggregates and
persists after every child completes.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from core.models.workflows import Workflow
from models.workflow_context import StepOutcome, WorkflowContext
from services.execution.graph import topological_generations
from services.execution.step_runner.signals import classify_step_exception

if TYPE_CHECKING:
    from services.execution.step_runner.runner import StepRunner

logger = logging.getLogger(__name__)


def _subgraph_node_blocked(
    runner: StepRunner,
    *,
    node_id: str,
    step_type: str,
    edges: list[dict[str, Any]],
    step_outcomes: dict[str, dict[str, WorkflowContext]],
    blocked_nodes: set[str],
    run_id: int,
) -> bool:
    if runner._step_requires_devices(step_type) and runner._blocked_by_upstream_failure(
        node_id, edges, step_outcomes, blocked_nodes
    ):
        blocked_nodes.add(node_id)
        logger.info(
            "Subgraph step skipped (blocked by upstream device failure) "
            "node_id=%s type=%s run_id=%s",
            node_id,
            step_type,
            run_id,
        )
        return True
    return False


async def _execute_one_subgraph_node(
    runner: StepRunner,
    *,
    run: WorkflowRun,
    workflow: Workflow,
    node_id: str,
    step_type: str,
    step_config: dict[str, Any],
    edges: list[dict[str, Any]],
    step_outcomes: dict[str, dict[str, WorkflowContext]],
) -> None:
    logger.info(
        "Subgraph step started node_id=%s type=%s run_id=%s",
        node_id,
        step_type,
        run.id,
    )
    input_context = runner._assemble_input_context(
        run=run,
        workflow=workflow,
        node_id=node_id,
        edges=edges,
        step_outcomes=step_outcomes,
    )
    outcomes = await runner._execute_step(
        step_type=step_type,
        config=step_config,
        context=input_context,
        run=run,
        node_id=node_id,
    )
    outcomes = runner._seed_run_inputs(run, outcomes)
    runner._store_step_outcomes(step_outcomes, node_id, outcomes)
    summaries = "; ".join(f"{o.name}: {o.summary}" for o in outcomes if o.summary)
    logger.info(
        "Subgraph step finished node_id=%s type=%s%s",
        node_id,
        step_type,
        f" summary={summaries}" if summaries else "",
    )


def _record_subgraph_node_error(
    runner: StepRunner,
    *,
    node_id: str,
    step_type: str,
    run_id: int,
    exc: Exception,
    step_errors: dict[str, dict[str, str]],
    step_outcomes: dict[str, dict[str, WorkflowContext]],
    initial_context: WorkflowContext,
) -> None:
    error_id = str(uuid.uuid4())
    category, message = classify_step_exception(exc)
    logger.error(
        "Subgraph step failed node_id=%s type=%s run_id=%s error_id=%s category=%s",
        node_id,
        step_type,
        run_id,
        error_id,
        category,
        exc_info=True,
        extra={"error_id": error_id},
    )
    step_errors[node_id] = {
        "message": message[:4000],
        "category": category,
        "error_id": error_id,
    }
    runner._store_step_outcomes(
        step_outcomes, node_id, [StepOutcome(name="failure", context=initial_context)]
    )


async def _run_one_subgraph_node(
    runner: StepRunner,
    *,
    run: WorkflowRun,
    workflow: Workflow,
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    step_outcomes: dict[str, dict[str, WorkflowContext]],
    step_errors: dict[str, dict[str, str]],
    blocked_nodes: set[str],
    initial_context: WorkflowContext,
) -> None:
    """Run (or block, or record the error for) one subgraph node.

    Mutates ``step_outcomes``/``step_errors``/``blocked_nodes`` in place —
    safe to call concurrently for every node in one topological generation,
    since siblings never share a key (see ``run_subgraph``).
    """
    node_id: str = node.get("id", "")
    node_data: dict[str, Any] = node.get("data", {})
    step_type: str = node_data.get("kind", "unknown")
    step_config: dict[str, Any] = node_data.get("pluginConfig", {})

    if _subgraph_node_blocked(
        runner,
        node_id=node_id,
        step_type=step_type,
        edges=edges,
        step_outcomes=step_outcomes,
        blocked_nodes=blocked_nodes,
        run_id=run.id,
    ):
        return

    try:
        await _execute_one_subgraph_node(
            runner,
            run=run,
            workflow=workflow,
            node_id=node_id,
            step_type=step_type,
            step_config=step_config,
            edges=edges,
            step_outcomes=step_outcomes,
        )
    except Exception as exc:
        _record_subgraph_node_error(
            runner,
            node_id=node_id,
            step_type=step_type,
            run_id=run.id,
            exc=exc,
            step_errors=step_errors,
            step_outcomes=step_outcomes,
            initial_context=initial_context,
        )


async def run_subgraph(
    runner: StepRunner,
    *,
    run: WorkflowRun,
    workflow: Workflow,
    initial_context: WorkflowContext,
    inventory_node_id: str,
    allowed_node_ids: set[str],
) -> tuple[dict[str, dict[str, WorkflowContext]], dict[str, dict[str, str]]]:
    """Run only the downstream subgraph without writing WorkflowStepResult records.

    Used by child workflows during fan-out. The parent aggregates and persists
    the returned step outcomes. Nodes with no dependency on one another (the
    same topological generation) run concurrently — see module docstring.

    Args:
        runner: The StepRunner instance whose per-node primitives this walk reuses.
        run: The parent WorkflowRun (read-only DB access via object_session).
        workflow: The workflow definition containing nodes and edges.
        initial_context: The WorkflowContext with the device subset for this child.
        inventory_node_id: The node_id of the inventory step that triggered fan-out.
        allowed_node_ids: Set of node IDs this child should execute.

    Returns:
        A tuple of:
        - Mapping of node_id → outcome_name → WorkflowContext for all executed nodes.
        - Mapping of node_id → {"message", "category", "error_id"} for nodes whose
          executor raised (see ``classify_step_exception``); the parent folds this
          into the persisted WorkflowStepResult.error_message/error_category/error_id.
    """
    nodes, edges = runner.load_execution_graph(workflow)
    ordered_nodes = runner._topological_sort(nodes, edges)
    subgraph_nodes = [n for n in ordered_nodes if n.get("id", "") in allowed_node_ids]

    step_outcomes: dict[str, dict[str, WorkflowContext]] = {
        inventory_node_id: {"success": initial_context}
    }
    step_errors: dict[str, dict[str, str]] = {}
    blocked_nodes: set[str] = set()

    for wave in topological_generations(subgraph_nodes, edges):
        await asyncio.gather(
            *(
                _run_one_subgraph_node(
                    runner,
                    run=run,
                    workflow=workflow,
                    node=node,
                    edges=edges,
                    step_outcomes=step_outcomes,
                    step_errors=step_errors,
                    blocked_nodes=blocked_nodes,
                    initial_context=initial_context,
                )
                for node in wave
            )
        )

    return step_outcomes, step_errors
