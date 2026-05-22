"""Executes all steps of a workflow run in topological order.

Returns True when all steps succeed, False when any step fails (remaining steps
are marked skipped). Never raises — the caller (Hatchet step) decides how to
interpret the return value.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.workflows import Workflow
from repositories.run_repository import RunRepository
from services.validation.step_output_validator import StepOutputValidator

_validator = StepOutputValidator()

logger = logging.getLogger(__name__)


class StepRunner:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RunRepository(db)

    async def execute_all(self, *, run: WorkflowRun, workflow: Workflow) -> bool:
        """Execute every step in dependency order. Returns True on full success."""
        nodes: list[dict[str, Any]] = workflow.canvas_nodes or []
        edges: list[dict[str, Any]] = workflow.canvas_edges or []

        ordered_nodes = self._topological_sort(nodes, edges)

        # Pre-create step result rows (all pending)
        step_results: dict[str, WorkflowStepResult] = {}
        for node in ordered_nodes:
            node_id: str = node.get("id", "")
            node_data: dict[str, Any] = node.get("data", {})
            step_type: str = node_data.get("kind", "unknown")
            step_name: str = node_data.get("title", step_type)
            step_results[node_id] = self.repo.create_step_result(
                run_id=run.id,
                step_node_id=node_id,
                step_type=step_type,
                step_name=step_name,
            )

        step_outputs: dict[str, Any] = {}
        failed = False

        for node in ordered_nodes:
            node_id = node.get("id", "")
            step_result = step_results[node_id]
            node_data = node.get("data", {})
            step_type = node_data.get("kind", "unknown")
            step_config: dict[str, Any] = node_data.get("pluginConfig", {})

            if failed:
                self.repo.update_step_result(step_result, status="skipped")
                continue

            parent_outputs = self._gather_parent_outputs(node_id, edges, step_outputs)

            self.repo.update_step_result(
                step_result,
                status="running",
                started_at=datetime.now(timezone.utc),
            )

            try:
                output = await self._execute_step(
                    step_type=step_type,
                    config=step_config,
                    parent_outputs=parent_outputs,
                    run=run,
                )
                step_outputs[node_id] = output
                self.repo.update_step_result(
                    step_result,
                    status="success",
                    output=output,
                    finished_at=datetime.now(timezone.utc),
                )
                logger.info("Step succeeded node_id=%s type=%s", node_id, step_type)
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
                failed = True

        return not failed

    async def _execute_step(
        self,
        *,
        step_type: str,
        config: dict[str, Any],
        parent_outputs: dict[str, Any],
        run: WorkflowRun,
    ) -> dict[str, Any]:
        from services.execution.step_registry import STEP_OUTPUT_TYPES, STEP_REGISTRY

        executor = STEP_REGISTRY.get(step_type)
        if executor is None:
            raise ValueError(f"Unknown step type: {step_type!r}")

        output = await executor(config=config, parent_outputs=parent_outputs, run=run)

        data_type = STEP_OUTPUT_TYPES.get(step_type)
        if data_type:
            result = _validator.validate(data_type, output)
            if not result.valid:
                raise ValueError(
                    f"Output validation failed for step '{step_type}' "
                    f"(data_type={data_type}): {'; '.join(result.errors)}"
                )

        return output

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

    def _gather_parent_outputs(
        self,
        node_id: str,
        edges: list[dict[str, Any]],
        step_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        parent_outputs: dict[str, Any] = {}
        for edge in edges:
            if edge.get("target") == node_id:
                src = edge.get("source", "")
                if src in step_outputs:
                    parent_outputs[src] = step_outputs[src]
        return parent_outputs
