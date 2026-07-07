"""Executes all steps of a workflow run in topological order.

Returns True when all steps succeed, False when any step fails (remaining steps
are marked skipped). Returns FanOutSignal when an inventory step requests
per-device fan-out via Hatchet child workflows. Never raises — the caller
(Hatchet step) decides how to interpret the return value.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.workflows import Workflow
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.plugin_repository import PluginRepository
from repositories.run_repository import RunRepository
from services.artifacts import FilesystemArtifactService
from services.execution.step_result_status import derive_step_result_status
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.guards import (
    effective_produces,
    post_step_guard,
    pre_step_guard,
)
from services.workflow_context.merge import merge_workflow_contexts
from services.workflow_context.registry import capability_spec_from_plugin


@dataclass
class FanOutSignal:
    """Returned by execute_all when an inventory step requests fan-out."""

    inventory_node_id: str
    fan_out_config: dict[str, Any]
    inventory_outcome: WorkflowContext  # context with all devices + _fan_out metadata
    step_outcomes: dict[str, dict[str, WorkflowContext]] = field(default_factory=dict)
    # node_id of the fan-in (join) step downstream of the inventory step, if any.
    # When set, children stop before it and the parent runs it (and everything
    # downstream of it) once on the merged context. When None, children run the
    # whole downstream subgraph (legacy behaviour).
    join_node_id: str | None = None

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _plugin_registry_service() -> PluginRegistryService:
    service = PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))
    service.load_registry()
    return service


class StepRunner:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RunRepository(db)
        self.artifact_service = FilesystemArtifactService(settings.data_directory)
        self.plugin_registry = _plugin_registry_service()

    async def execute_all(
        self, *, run: WorkflowRun, workflow: Workflow
    ) -> bool | FanOutSignal:
        """Execute every step in dependency order.

        Returns True on full success, False when any step fails (remaining steps
        are marked skipped). Returns FanOutSignal when an inventory step embeds
        ``_fan_out.enabled`` in its outcome context — the caller must handle
        dispatching child workflows and aggregating results.
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []

        ordered_nodes = self.build_execution_plan(nodes, edges)
        step_results = self.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

        # node_id -> outcome_name -> WorkflowContext
        step_outcomes: dict[str, dict[str, WorkflowContext]] = {}
        failed = False

        for node in ordered_nodes:
            node_id = node.get("id", "")
            step_result = step_results[node_id]

            if failed:
                self.repo.update_step_result(step_result, status="skipped")
                continue

            ok = await self._execute_and_persist_node(
                node=node,
                run=run,
                workflow=workflow,
                edges=edges,
                step_outcomes=step_outcomes,
                step_result=step_result,
            )
            if not ok:
                failed = True
                continue

            # Check if this step requested fan-out. When it does, stop here and
            # hand control back to the orchestrator, which dispatches children
            # and (when a fan-in node exists) resumes execution after the join.
            success_ctx = step_outcomes.get(node_id, {}).get("success")
            if success_ctx and success_ctx.metadata.get("_fan_out", {}).get("enabled"):
                fan_out_config = dict(success_ctx.metadata["_fan_out"])
                join_node_id = self._find_join_node_id(node_id, nodes, edges)
                logger.info(
                    "Fan-out requested node_id=%s mode=%s join_node_id=%s run_id=%s",
                    node_id,
                    fan_out_config.get("mode"),
                    join_node_id,
                    run.id,
                )
                return FanOutSignal(
                    inventory_node_id=node_id,
                    fan_out_config=fan_out_config,
                    inventory_outcome=success_ctx,
                    step_outcomes=dict(step_outcomes),
                    join_node_id=join_node_id,
                )

        return not failed

    def build_execution_plan(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return canvas nodes in dependency (topological) order.

        Public entry point for callers that drive the walk themselves, e.g. the
        Hatchet task's debug-mode per-node loop (`hatchet/workflows/workflow_run.py`).
        """
        return self._topological_sort(nodes, edges)

    def create_pending_step_results(
        self, *, run_id: int, ordered_nodes: list[dict[str, Any]]
    ) -> dict[str, WorkflowStepResult]:
        """Pre-create a pending WorkflowStepResult row for every node in the plan."""
        step_results: dict[str, WorkflowStepResult] = {}
        for node in ordered_nodes:
            node_id: str = node.get("id", "")
            node_data: dict[str, Any] = node.get("data", {})
            step_type: str = node_data.get("kind", "unknown")
            step_name: str = node_data.get("title", step_type)
            step_results[node_id] = self.repo.create_step_result(
                run_id=run_id,
                step_node_id=node_id,
                step_type=step_type,
                step_name=step_name,
            )
        return step_results

    async def execute_one(
        self,
        *,
        node: dict[str, Any],
        run: WorkflowRun,
        workflow: Workflow,
        edges: list[dict[str, Any]],
        step_outcomes: dict[str, dict[str, WorkflowContext]],
        step_result: WorkflowStepResult,
    ) -> bool:
        """Execute exactly one node and persist its result.

        Public entry point for callers that drive the topological walk
        themselves (debug-mode stepping in the Hatchet task) instead of using
        `execute_all`. Thin wrapper around `_execute_and_persist_node` so the
        dispatch/guard/serialize logic lives in exactly one place.
        """
        return await self._execute_and_persist_node(
            node=node,
            run=run,
            workflow=workflow,
            edges=edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
        )

    async def _execute_and_persist_node(
        self,
        *,
        node: dict[str, Any],
        run: WorkflowRun,
        workflow: Workflow,
        edges: list[dict[str, Any]],
        step_outcomes: dict[str, dict[str, WorkflowContext]],
        step_result: WorkflowStepResult,
    ) -> bool:
        """Execute one node, store its outcomes, and persist its step result.

        Returns True when the step ran (even with device-level failures, e.g. a
        ``partial`` outcome) and False only when the executor raised. Shared by
        ``execute_all`` and ``resume_after_join`` so the dispatch/guard/serialize
        logic lives in exactly one place.
        """
        node_id = node.get("id", "")
        node_data = node.get("data", {})
        step_type = node_data.get("kind", "unknown")
        step_config: dict[str, Any] = node_data.get("pluginConfig", {})

        self.repo.update_step_result(
            step_result,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        logger.info(
            "Step started node_id=%s type=%s run_id=%s",
            node_id,
            step_type,
            run.id,
        )

        try:
            input_context = self._assemble_input_context(
                run=run,
                workflow=workflow,
                node_id=node_id,
                edges=edges,
                step_outcomes=step_outcomes,
            )
            outcomes = await self._execute_step(
                step_type=step_type,
                config=step_config,
                context=input_context,
                run=run,
                node_id=node_id,
            )
            self._store_step_outcomes(step_outcomes, node_id, outcomes)

            persisted_output = self._serialize_outcomes(outcomes)
            step_status = derive_step_result_status(
                outcomes=outcomes,
                input_context=input_context,
            )
            self.repo.update_step_result(
                step_result,
                status=step_status,
                output=persisted_output,
                finished_at=datetime.now(timezone.utc),
            )
            summaries = "; ".join(f"{o.name}: {o.summary}" for o in outcomes if o.summary)
            logger.info(
                "Step finished node_id=%s type=%s status=%s%s",
                node_id,
                step_type,
                step_status,
                f" summary={summaries}" if summaries else "",
            )
            return True
        except Exception:
            logger.error(
                "Step failed node_id=%s type=%s run_id=%s",
                node_id,
                step_type,
                run.id,
                exc_info=True,
            )
            import traceback

            self.repo.update_step_result(
                step_result,
                status="failed",
                error_message=traceback.format_exc()[:4000],
                finished_at=datetime.now(timezone.utc),
            )
            return False

    async def resume_after_join(
        self,
        *,
        run: WorkflowRun,
        workflow: Workflow,
        merged_outcomes: dict[str, dict[str, WorkflowContext]],
        join_node_id: str,
    ) -> bool:
        """Run the fan-in node and everything downstream of it exactly once.

        Called by the orchestrator after all fan-out children complete. The
        ``merged_outcomes`` map (node_id -> outcome_name -> merged WorkflowContext)
        must contain every node that is a parent of the join — typically the
        boundary child nodes plus the inventory node — so ``_assemble_input_context``
        can resolve the fan-in node's inputs from the fanned-in device union.

        Writes/updates WorkflowStepResult rows for the post-join nodes on the
        parent run. Returns True when every post-join step ran without raising
        (device-level ``partial`` results still count as success here, matching
        the proceed-with-survivors policy).
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []
        ordered_nodes = self._topological_sort(nodes, edges)

        post_join_ids = {join_node_id} | self._downstream_node_ids(
            join_node_id, nodes, edges
        )

        # Seed prior outcomes from the children so the fan-in node's parents resolve.
        step_outcomes: dict[str, dict[str, WorkflowContext]] = {
            node_id: dict(outcomes) for node_id, outcomes in merged_outcomes.items()
        }

        step_result_by_node: dict[str, WorkflowStepResult] = {
            sr.step_node_id: sr for sr in self.repo.get_step_results_for_run(run.id)
        }

        failed = False
        for node in ordered_nodes:
            node_id = node.get("id", "")
            if node_id not in post_join_ids:
                continue

            step_result = step_result_by_node.get(node_id)
            if step_result is None:
                node_data = node.get("data", {})
                step_result = self.repo.create_step_result(
                    run_id=run.id,
                    step_node_id=node_id,
                    step_type=node_data.get("kind", "unknown"),
                    step_name=node_data.get("title", node_data.get("kind", "unknown")),
                )

            if failed:
                self.repo.update_step_result(step_result, status="skipped")
                continue

            ok = await self._execute_and_persist_node(
                node=node,
                run=run,
                workflow=workflow,
                edges=edges,
                step_outcomes=step_outcomes,
                step_result=step_result,
            )
            if not ok:
                failed = True

        return not failed

    async def execute_subgraph(
        self,
        *,
        run: WorkflowRun,
        workflow: Workflow,
        initial_context: WorkflowContext,
        inventory_node_id: str,
        allowed_node_ids: set[str],
    ) -> dict[str, dict[str, WorkflowContext]]:
        """Run only the downstream subgraph without writing WorkflowStepResult records.

        Used by child workflows during fan-out. The parent aggregates and persists
        the returned step outcomes.

        Args:
            run: The parent WorkflowRun (read-only DB access via object_session).
            workflow: The workflow definition containing nodes and edges.
            initial_context: The WorkflowContext with the device subset for this child.
            inventory_node_id: The node_id of the inventory step that triggered fan-out.
            allowed_node_ids: Set of node IDs this child should execute.

        Returns:
            Mapping of node_id → outcome_name → WorkflowContext for all executed nodes.
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []
        ordered_nodes = self._topological_sort(nodes, edges)

        step_outcomes: dict[str, dict[str, WorkflowContext]] = {
            inventory_node_id: {"success": initial_context}
        }

        for node in ordered_nodes:
            node_id: str = node.get("id", "")
            if node_id not in allowed_node_ids:
                continue

            node_data: dict[str, Any] = node.get("data", {})
            step_type: str = node_data.get("kind", "unknown")
            step_config: dict[str, Any] = node_data.get("pluginConfig", {})

            logger.info(
                "Subgraph step started node_id=%s type=%s run_id=%s",
                node_id,
                step_type,
                run.id,
            )
            try:
                input_context = self._assemble_input_context(
                    run=run,
                    workflow=workflow,
                    node_id=node_id,
                    edges=edges,
                    step_outcomes=step_outcomes,
                )
                outcomes = await self._execute_step(
                    step_type=step_type,
                    config=step_config,
                    context=input_context,
                    run=run,
                    node_id=node_id,
                )
                self._store_step_outcomes(step_outcomes, node_id, outcomes)
                summaries = "; ".join(f"{o.name}: {o.summary}" for o in outcomes if o.summary)
                logger.info(
                    "Subgraph step finished node_id=%s type=%s%s",
                    node_id,
                    step_type,
                    f" summary={summaries}" if summaries else "",
                )
            except Exception:
                logger.error(
                    "Subgraph step failed node_id=%s type=%s run_id=%s",
                    node_id,
                    step_type,
                    run.id,
                    exc_info=True,
                )
                self._store_step_outcomes(
                    step_outcomes, node_id, [StepOutcome(name="failure", context=initial_context)]
                )

        return step_outcomes

    @staticmethod
    def _downstream_node_ids(
        start_node_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> set[str]:
        """Return all node IDs reachable downstream of start_node_id (excluding it)."""
        adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes if "id" in n}
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in adjacency and tgt in adjacency:
                adjacency[src].append(tgt)

        visited: set[str] = set()
        queue: deque[str] = deque(adjacency.get(start_node_id, []))
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            queue.extend(adjacency.get(nid, []))
        return visited

    @staticmethod
    def _find_join_node_id(
        inventory_node_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> str | None:
        """Return the first fan-in node downstream of the inventory step, if any.

        v1 supports at most one fan-in node per fanned-out branch; the match is
        deterministic by node list order.
        """
        downstream = StepRunner._downstream_node_ids(inventory_node_id, nodes, edges)
        for node in nodes:
            node_id = node.get("id", "")
            if node_id in downstream and (node.get("data", {}) or {}).get("kind") == "fan-in":
                return node_id
        return None

    @staticmethod
    def _child_node_ids(
        inventory_node_id: str,
        join_node_id: str | None,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> set[str]:
        """Nodes a fan-out child should execute.

        That is everything downstream of the inventory step, minus the fan-in
        node and everything downstream of it (which the parent runs once after
        the children rejoin). When no fan-in node exists, children run the whole
        downstream subgraph (legacy behaviour).
        """
        downstream = StepRunner._downstream_node_ids(inventory_node_id, nodes, edges)
        if join_node_id is None:
            return downstream
        post_join = {join_node_id} | StepRunner._downstream_node_ids(
            join_node_id, nodes, edges
        )
        return downstream - post_join

    def _assemble_input_context(
        self,
        *,
        run: WorkflowRun,
        workflow: Workflow,
        node_id: str,
        edges: list[dict[str, Any]],
        step_outcomes: dict[str, dict[str, WorkflowContext]],
    ) -> WorkflowContext:
        parent_contexts: list[WorkflowContext] = []
        for edge in edges:
            if edge.get("target") != node_id:
                continue
            source_id = edge.get("source", "")
            outcome_name = edge.get("sourceHandle") or "success"
            parent_outcome = step_outcomes.get(source_id, {}).get(outcome_name)
            if parent_outcome is not None:
                parent_contexts.append(parent_outcome)

        if not parent_contexts:
            return WorkflowContext(run_id=run.uuid, workflow_id=str(workflow.id))

        return merge_workflow_contexts(parent_contexts)

    async def _execute_step(
        self,
        *,
        step_type: str,
        config: dict[str, Any],
        context: WorkflowContext,
        run: WorkflowRun,
        node_id: str,
    ) -> list[StepOutcome]:
        from services.execution.step_registry import STEP_REGISTRY

        executor = STEP_REGISTRY.get(step_type)
        if executor is None:
            raise ValueError(f"Unknown step type: {step_type!r}")

        plugin = self.plugin_registry.get_plugin(step_type)
        if plugin is None:
            raise ValueError(f"Unknown plugin in registry: {step_type!r}")

        spec = capability_spec_from_plugin(plugin)
        pre_step_guard(spec=spec, context=context)

        outcomes = await executor(
            config=config,
            context=context,
            run=run,
            artifact_service=self.artifact_service,
            node_id=node_id,
        )
        if not outcomes:
            raise RuntimeError(f"Step {step_type!r} returned no outcomes")

        post_step_guard(
            spec=spec,
            input_context=context,
            outcomes=outcomes,
            expected_produces=effective_produces(
                spec=spec,
                step_type=step_type,
                config=config,
            ),
        )
        return outcomes

    @staticmethod
    def _store_step_outcomes(
        step_outcomes: dict[str, dict[str, WorkflowContext]],
        node_id: str,
        outcomes: list[StepOutcome],
    ) -> None:
        step_outcomes[node_id] = {outcome.name: outcome.context for outcome in outcomes}

    @staticmethod
    def _serialize_outcomes(outcomes: list[StepOutcome]) -> dict[str, Any]:
        return {
            "outcomes": {
                outcome.name: outcome.context.model_dump(mode="json")
                for outcome in outcomes
            }
        }

    def _topological_sort(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        node_map = {n["id"]: n for n in nodes if "id" in n}
        in_degree: dict[str, int] = {nid: 0 for nid in node_map}
        dependents: dict[str, list[str]] = {nid: [] for nid in node_map}

        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in in_degree and tgt in in_degree:
                in_degree[tgt] += 1
                dependents[src].append(tgt)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result: list[dict[str, Any]] = []

        while queue:
            nid = queue.pop(0)
            result.append(node_map[nid])
            for dep in dependents[nid]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        return result
