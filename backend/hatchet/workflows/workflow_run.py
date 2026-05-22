from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from hatchet_sdk import Context

from hatchet.client import hatchet

logger = logging.getLogger(__name__)


class WorkflowRunInput(BaseModel):
    run_id: int


workflow = hatchet.workflow(
    name="WorkflowExecution",
    on_events=["workflow:run"],
    input_validator=WorkflowRunInput,
)


@workflow.task(name="prepare", execution_timeout=timedelta(seconds=30))
async def prepare(input: WorkflowRunInput, ctx: Context) -> dict:
    logger.info("Preparing workflow run run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository

    with SessionLocal() as db:
        repo = RunRepository(db)
        result = repo.get_run_by_id(input.run_id)
        if result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found")
        run, _ = result
        repo.update_run_status(
            run,
            status="running",
            started_at=datetime.now(timezone.utc),
        )

    return {"run_id": input.run_id}


@workflow.task(name="execute_steps", parents=[prepare], execution_timeout=timedelta(hours=1))
async def execute_steps(input: WorkflowRunInput, ctx: Context) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)

    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

    with SessionLocal() as db:
        run_repo = RunRepository(db)
        wf_repo = WorkflowRepository(db)

        run_result = run_repo.get_run_by_id(input.run_id)
        if run_result is None:
            raise ValueError(f"WorkflowRun {input.run_id} not found")
        run, _ = run_result

        wf_result = wf_repo.get_by_id(run.workflow_id)
        if wf_result is None:
            raise ValueError(f"Workflow {run.workflow_id} not found")
        wf, _ = wf_result

        runner = StepRunner(db)
        success = await runner.execute_all(run=run, workflow=wf)

        final_status = "success" if success else "failed"
        run_repo.update_run_status(
            run,
            status=final_status,
            finished_at=datetime.now(timezone.utc),
        )
        logger.info("Run finished run_id=%s status=%s", input.run_id, final_status)

    return {"run_id": input.run_id, "status": final_status}
