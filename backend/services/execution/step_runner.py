"""Executes all steps of a workflow run in topological order.

Returns True when all steps succeed, False when any step fails (remaining steps
are marked skipped). Returns FanOutSignal when an inventory step requests
per-device fan-out via Hatchet child workflows. Never raises — the caller
(Hatchet step) decides how to interpret the return value.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.workflows import Workflow
from models.workflow_context import Capability, StepOutcome, WorkflowContext
from repositories.plugin_repository import PluginRepository
from repositories.run_repository import RunRepository
from services.artifacts import FilesystemArtifactService
from services.execution.graph import (
    downstream_node_ids,
    find_join_node_id,
    topological_order,
)
from services.execution.step_result_status import derive_step_result_status
from services.network.netmiko.session_pool import DeviceSessionPool
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.guards import (
    effective_produces,
    post_step_guard,
    pre_step_guard,
)
from services.workflow_context.merge import merge_workflow_contexts
from services.workflow_context.registry import capability_spec_from_plugin
from services.workflow_context.run_inputs import seed_run_input_bag
from services.workflow_context.secret_fields import redact_secrets_in_data


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


def classify_step_exception(exc: Exception) -> tuple[str, str]:
    """Map a raised exception to (error_category, user-facing message).

    Steps follow the convention documented in doc/WORKFLOW-STEPS.md: raise
    ``ValueError`` for configuration problems (missing/invalid settings,
    unresolved references) and ``RuntimeError`` for expected-but-failed
    execution conditions (e.g. a device unreachable). Both are authored by
    step code with human-readable messages, so it's safe to show them
    directly. Anything else is an unanticipated bug — its message may
    contain internals (paths, library-specific text) so it's withheld;
    only the error_id (correlatable with the full traceback in worker
    logs) is shown.
    """
    if isinstance(exc, ValueError):
        return "configuration", str(exc) or "This step's configuration is invalid."
    if isinstance(exc, RuntimeError):
        return "execution", str(exc) or "This step failed to complete."
    return "internal", "An unexpected internal error occurred while running this step."


@lru_cache(maxsize=1)
def _plugin_registry_service() -> PluginRegistryService:
    service = PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))
    service.load_registry()
    return service


class StepRunner:
    """Executes the steps of one execution segment (a phase-1 walk, a phase-4
    post-join resume, or a fan-out child's subgraph).

    Owns a ``DeviceSessionPool`` (``self.device_sessions``) scoped to that
    segment. Ownership rule: whoever instantiates ``StepRunner`` must
    ``finally: await runner.close_device_sessions()`` — see
    doc/DURABLE_SSH_SESSION.md §5.4/§5.5/§5.6 for the call sites.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RunRepository(db)
        self.artifact_service = FilesystemArtifactService(settings.data_directory)
        self.plugin_registry = _plugin_registry_service()
        self.device_sessions = DeviceSessionPool(
            max_workers=settings.netmiko_pool_workers,
            enabled=settings.netmiko_session_pooling,
        )

    async def suspend_device_sessions(self) -> None:
        """Disconnect all live device sessions before a durable wait; the pool
        stays usable and reconnects lazily on the next network step."""
        await self.device_sessions.suspend()

    async def close_device_sessions(self) -> None:
        """Disconnect everything and shut down the pool's thread executor.
        Idempotent — safe to call even if the pool was never used."""
        await self.device_sessions.close()

    async def execute_all(self, *, run: WorkflowRun, workflow: Workflow) -> bool | FanOutSignal:
        """Execute every step in dependency order.

        Returns True on full success, False when any step fails (remaining steps
        are marked skipped) or when any step's own device outcome indicates
        failure — including a downstream step that never ran because every
        device that could have reached it was lost to an earlier failure (see
        ``run_node_in_sequence``). Returns FanOutSignal when an inventory step
        embeds ``_fan_out.enabled`` in its outcome context — the caller must
        handle dispatching child workflows and aggregating results.
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []

        ordered_nodes = self.build_execution_plan(nodes, edges)
        step_results = self.create_pending_step_results(run_id=run.id, ordered_nodes=ordered_nodes)

        # node_id -> outcome_name -> WorkflowContext
        step_outcomes: dict[str, dict[str, WorkflowContext]] = {}
        blocked_nodes: set[str] = set()
        failed = False
        any_reported_failure = False

        for node in ordered_nodes:
            node_id = node.get("id", "")
            step_result = step_results[node_id]

            if failed:
                self.repo.update_step_result(step_result, status="skipped")
                continue

            raised, indicates_failure = await self.run_node_in_sequence(
                node=node,
                run=run,
                workflow=workflow,
                edges=edges,
                step_outcomes=step_outcomes,
                step_result=step_result,
                blocked_nodes=blocked_nodes,
            )
            if raised:
                failed = True
                continue
            if indicates_failure:
                any_reported_failure = True

            # Check if this step requested fan-out. When it does, stop here and
            # hand control back to the orchestrator, which dispatches children
            # and (when a fan-in node exists) resumes execution after the join.
            success_ctx = step_outcomes.get(node_id, {}).get("success")
            if success_ctx and success_ctx.metadata.get("_fan_out", {}).get("enabled"):
                fan_out_config = dict(success_ctx.metadata["_fan_out"])
                join_node_id = find_join_node_id(node_id, nodes, edges)
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

        return not (failed or any_reported_failure)

    def build_execution_plan(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return canvas nodes in dependency (topological) order.

        Canvas decorations (``executable: false`` in the plugin registry) are
        excluded — they persist on the canvas for layout only and never run.

        Public entry point for callers that drive the walk themselves, e.g. the
        Hatchet task's debug-mode per-node loop (`hatchet/workflows/workflow_run.py`).
        """
        return self._topological_sort(nodes, edges)

    def _is_executable_node(self, node: dict[str, Any]) -> bool:
        """False for canvas decorations (label, background, …); True otherwise.

        Unknown kinds stay executable so StepRunner still fails with
        ``Unknown step type`` rather than silently dropping them.
        """
        kind = (node.get("data") or {}).get("kind", "")
        if not kind:
            return True
        plugin = self.plugin_registry.get_plugin(kind)
        if plugin is None:
            return True
        return plugin.executable

    def _filter_executable_graph(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Drop non-executable decoration nodes and any edges that touch them."""
        executable_nodes = [n for n in nodes if self._is_executable_node(n)]
        executable_ids = {n["id"] for n in executable_nodes if "id" in n}
        executable_edges = [
            e
            for e in edges
            if e.get("source", "") in executable_ids and e.get("target", "") in executable_ids
        ]
        return executable_nodes, executable_edges

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

    def _step_requires_devices(self, step_type: str) -> bool:
        """True when this step's registry entry declares it needs devices
        (``requires: [identity, ...]``) rather than being device-agnostic."""
        plugin = self.plugin_registry.get_plugin(step_type)
        if plugin is None:
            return False
        return Capability.IDENTITY in capability_spec_from_plugin(plugin).requires

    @staticmethod
    def _blocked_by_upstream_failure(
        node_id: str,
        edges: list[dict[str, Any]],
        step_outcomes: dict[str, dict[str, WorkflowContext]],
        blocked_nodes: set[str],
    ) -> bool:
        """True when every device that could have reached this node was lost
        to a real upstream failure — not merely because an inventory step (or
        a filter) legitimately matched zero devices. Distinguishing the two
        matters: a run shouldn't read as failed just because a filter matched
        nothing, only when something actually failed upstream.

        A node counts as blocked when at least one parent edge shows failure
        evidence (the parent's own ``failure`` outcome has devices, or the
        parent itself was already blocked) and none of its parent edges
        actually delivered devices.
        """
        parent_edges = [edge for edge in edges if edge.get("target") == node_id]
        if not parent_edges:
            return False

        saw_devices = False
        saw_failure_evidence = False
        for edge in parent_edges:
            source_id = edge.get("source", "")
            if source_id in blocked_nodes:
                saw_failure_evidence = True
                continue
            outcome_name = edge.get("sourceHandle") or "success"
            parent_outcomes = step_outcomes.get(source_id) or {}
            outcome_ctx = parent_outcomes.get(outcome_name)
            if outcome_ctx is not None and outcome_ctx.devices:
                saw_devices = True
            failure_ctx = parent_outcomes.get("failure")
            if failure_ctx is not None and failure_ctx.devices:
                saw_failure_evidence = True

        return saw_failure_evidence and not saw_devices

    async def run_node_in_sequence(
        self,
        *,
        node: dict[str, Any],
        run: WorkflowRun,
        workflow: Workflow,
        edges: list[dict[str, Any]],
        step_outcomes: dict[str, dict[str, WorkflowContext]],
        step_result: WorkflowStepResult,
        blocked_nodes: set[str],
    ) -> tuple[bool, bool]:
        """Run one node in a topological walk, handling the "blocked by an
        upstream device failure" pre-check before invoking the executor.

        Shared by ``execute_all``, ``resume_after_join``, and the Hatchet
        orchestrator's per-node loop so the check applies identically
        everywhere a canvas node gets executed and persisted.

        Returns ``(raised_exception, step_indicates_failure)``:

        - ``raised_exception``: the executor raised — callers should hard-stop
          (blanket-skip all remaining nodes), matching prior behaviour.
        - ``step_indicates_failure``: this node was skipped because every
          device that could have reached it was lost upstream, or it ran and
          failed for every device it saw. Either way the run's final status
          should be "failed" — but execution should keep going, since an
          independent branch (e.g. a failure-handler wired to the failing
          step's own ``failure`` handle) may still have real work to do.
        """
        node_id = node.get("id", "")
        step_type = (node.get("data", {}) or {}).get("kind", "unknown")

        if self._step_requires_devices(step_type) and self._blocked_by_upstream_failure(
            node_id, edges, step_outcomes, blocked_nodes
        ):
            self.repo.update_step_result(step_result, status="skipped")
            blocked_nodes.add(node_id)
            logger.info(
                "Step skipped (blocked by upstream device failure) node_id=%s type=%s run_id=%s",
                node_id,
                step_type,
                run.id,
            )
            return False, True

        ok = await self._execute_and_persist_node(
            node=node,
            run=run,
            workflow=workflow,
            edges=edges,
            step_outcomes=step_outcomes,
            step_result=step_result,
        )
        if not ok:
            return True, True
        return False, step_result.status == "failed"

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
            started_at=datetime.now(UTC),
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
            outcomes = self._seed_run_inputs(run, outcomes)
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
                finished_at=datetime.now(UTC),
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
        except Exception as exc:
            error_id = str(uuid.uuid4())
            category, message = classify_step_exception(exc)
            logger.error(
                "Step failed node_id=%s type=%s run_id=%s error_id=%s category=%s",
                node_id,
                step_type,
                run.id,
                error_id,
                category,
                exc_info=True,
                extra={"error_id": error_id},
            )
            self.repo.update_step_result(
                step_result,
                status="failed",
                error_message=message[:4000],
                error_category=category,
                error_id=error_id,
                finished_at=datetime.now(UTC),
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
        and without every device failing outright (device-level ``partial``
        results still count as success here, matching the proceed-with-survivors
        policy). A post-join node whose merged input is empty because every
        device failed earlier in the (already-merged) child branch is marked
        "skipped" rather than a trivial success — see
        ``run_node_in_sequence``/``_blocked_by_upstream_failure``. Note:
        ``blocked_nodes`` starts empty here, so this does not see failures from
        nodes that ran before the fan-out point in the same graph — an
        unusual shape in practice (post-join nodes are fed by the fanned-in
        device union, not pre-fan-out context).
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []
        ordered_nodes = self._topological_sort(nodes, edges)

        post_join_ids = {join_node_id} | downstream_node_ids(join_node_id, nodes, edges)

        # Seed prior outcomes from the children so the fan-in node's parents resolve.
        step_outcomes: dict[str, dict[str, WorkflowContext]] = {
            node_id: dict(outcomes) for node_id, outcomes in merged_outcomes.items()
        }

        step_result_by_node: dict[str, WorkflowStepResult] = {
            sr.step_node_id: sr for sr in self.repo.get_step_results_for_run(run.id)
        }

        blocked_nodes: set[str] = set()
        failed = False
        any_reported_failure = False
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

            raised, indicates_failure = await self.run_node_in_sequence(
                node=node,
                run=run,
                workflow=workflow,
                edges=edges,
                step_outcomes=step_outcomes,
                step_result=step_result,
                blocked_nodes=blocked_nodes,
            )
            if raised:
                failed = True
                continue
            if indicates_failure:
                any_reported_failure = True

        return not (failed or any_reported_failure)

    def _subgraph_node_blocked(
        self,
        *,
        node_id: str,
        step_type: str,
        edges: list[dict[str, Any]],
        step_outcomes: dict[str, dict[str, WorkflowContext]],
        blocked_nodes: set[str],
        run_id: int,
    ) -> bool:
        if self._step_requires_devices(step_type) and self._blocked_by_upstream_failure(
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
        self,
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
        outcomes = self._seed_run_inputs(run, outcomes)
        self._store_step_outcomes(step_outcomes, node_id, outcomes)
        summaries = "; ".join(f"{o.name}: {o.summary}" for o in outcomes if o.summary)
        logger.info(
            "Subgraph step finished node_id=%s type=%s%s",
            node_id,
            step_type,
            f" summary={summaries}" if summaries else "",
        )

    def _record_subgraph_node_error(
        self,
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
        self._store_step_outcomes(
            step_outcomes, node_id, [StepOutcome(name="failure", context=initial_context)]
        )

    async def execute_subgraph(
        self,
        *,
        run: WorkflowRun,
        workflow: Workflow,
        initial_context: WorkflowContext,
        inventory_node_id: str,
        allowed_node_ids: set[str],
    ) -> tuple[dict[str, dict[str, WorkflowContext]], dict[str, dict[str, str]]]:
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
            A tuple of:
            - Mapping of node_id → outcome_name → WorkflowContext for all executed nodes.
            - Mapping of node_id → {"message", "category", "error_id"} for nodes whose
              executor raised (see ``classify_step_exception``); the parent folds this
              into the persisted WorkflowStepResult.error_message/error_category/error_id.
        """
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []
        ordered_nodes = self._topological_sort(nodes, edges)

        step_outcomes: dict[str, dict[str, WorkflowContext]] = {
            inventory_node_id: {"success": initial_context}
        }
        step_errors: dict[str, dict[str, str]] = {}
        blocked_nodes: set[str] = set()

        for node in ordered_nodes:
            node_id: str = node.get("id", "")
            if node_id not in allowed_node_ids:
                continue

            node_data: dict[str, Any] = node.get("data", {})
            step_type: str = node_data.get("kind", "unknown")
            step_config: dict[str, Any] = node_data.get("pluginConfig", {})

            if self._subgraph_node_blocked(
                node_id=node_id,
                step_type=step_type,
                edges=edges,
                step_outcomes=step_outcomes,
                blocked_nodes=blocked_nodes,
                run_id=run.id,
            ):
                continue

            try:
                await self._execute_one_subgraph_node(
                    run=run,
                    workflow=workflow,
                    node_id=node_id,
                    step_type=step_type,
                    step_config=step_config,
                    edges=edges,
                    step_outcomes=step_outcomes,
                )
            except Exception as exc:
                self._record_subgraph_node_error(
                    node_id=node_id,
                    step_type=step_type,
                    run_id=run.id,
                    exc=exc,
                    step_errors=step_errors,
                    step_outcomes=step_outcomes,
                    initial_context=initial_context,
                )

        return step_outcomes, step_errors

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
            device_sessions=self.device_sessions,
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
    def _seed_run_inputs(run: WorkflowRun, outcomes: list[StepOutcome]) -> list[StepOutcome]:
        """Stamp WorkflowRun.run_inputs onto every device in each outcome's
        context — see services.workflow_context.run_inputs.seed_run_input_bag.
        No-op when the run declared no static attributes."""
        if not run.run_inputs:
            return outcomes
        return [
            StepOutcome(
                name=outcome.name,
                context=seed_run_input_bag(outcome.context, run.run_inputs),
                summary=outcome.summary,
            )
            for outcome in outcomes
        ]

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
                outcome.name: redact_secrets_in_data(outcome.context.model_dump(mode="json"))
                for outcome in outcomes
            }
        }

    def _topological_sort(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Executable-node-filtered topological order.

        Raises ``GraphCycleError`` (a ``ValueError``) if the graph contains a
        cycle — see ``services.execution.graph.topological_order``. Workflow
        definitions are also validated for cycles at save time
        (``WorkflowService``), but this is defense in depth: canvas data can
        change between save and run (e.g. direct DB edits, older saved
        workflows from before that validation existed).
        """
        executable_nodes, executable_edges = self._filter_executable_graph(nodes, edges)
        return topological_order(executable_nodes, executable_edges)
