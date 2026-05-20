from __future__ import annotations

import logging
from datetime import datetime, timezone

from hatchet_sdk import Context

from hatchet.client import hatchet

logger = logging.getLogger(__name__)


@hatchet.workflow(name="WorkflowExecution", on_events=["workflow:run"])
class WorkflowExecutionWorkflow:
    """Hatchet workflow that executes one workflow run end-to-end.

    Input payload: {"run_id": <int>}

    Steps:
      prepare          — mark run as running
      execute_steps    — run each canvas step in topological order (after prepare)
    """

    @hatchet.step(name="prepare", timeout="30s")
    async def prepare(self, context: Context) -> dict:
        run_id: int = context.workflow_input()["run_id"]
        logger.info("Preparing workflow run run_id=%s", run_id)

        from core.database import SessionLocal
        from repositories.run_repository import RunRepository

        with SessionLocal() as db:
            repo = RunRepository(db)
            result = repo.get_run_by_id(run_id)
            if result is None:
                raise ValueError(f"WorkflowRun {run_id} not found")
            run, _ = result
            repo.update_run_status(
                run,
                status="running",
                started_at=datetime.now(timezone.utc),
            )

        return {"run_id": run_id}

    @hatchet.step(name="execute_steps", parents=["prepare"], timeout="60m")
    async def execute_steps(self, context: Context) -> dict:
        run_id: int = context.workflow_input()["run_id"]
        logger.info("Executing steps for run_id=%s", run_id)

        from core.database import SessionLocal
        from repositories.run_repository import RunRepository
        from repositories.workflow_repository import WorkflowRepository
        from services.execution.step_runner import StepRunner

        with SessionLocal() as db:
            run_repo = RunRepository(db)
            wf_repo = WorkflowRepository(db)

            run_result = run_repo.get_run_by_id(run_id)
            if run_result is None:
                raise ValueError(f"WorkflowRun {run_id} not found")
            run, _ = run_result

            wf_result = wf_repo.get_by_id(run.workflow_id)
            if wf_result is None:
                raise ValueError(f"Workflow {run.workflow_id} not found")
            workflow, _ = wf_result

            runner = StepRunner(db)
            success = await runner.execute_all(run=run, workflow=workflow)

            final_status = "success" if success else "failed"
            run_repo.update_run_status(
                run,
                status=final_status,
                finished_at=datetime.now(timezone.utc),
            )
            logger.info("Run finished run_id=%s status=%s", run_id, final_status)

        return {"run_id": run_id, "status": final_status}
