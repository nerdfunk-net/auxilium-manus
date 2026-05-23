from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.models.users import User
from models.runs import WorkflowRunCreate, WorkflowRunListResponse, WorkflowRunResponse
from services.execution.run_service import RunService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["workflow-runs"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> RunService:
    return RunService(db)


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_run(
    workflow_id: int,
    body: WorkflowRunCreate,
    current_user: User = Depends(get_current_user),
    service: RunService = Depends(_service),
) -> WorkflowRunResponse:
    return service.trigger_run(workflow_id=workflow_id, data=body, user_id=current_user.id)


@router.get("/workflows/{workflow_id}/runs", response_model=WorkflowRunListResponse)
async def list_runs(
    workflow_id: int,
    status: list[str] | None = Query(
        None,
        description=(
            "Filter by run status (pending, running, success, failed, cancelled) "
            "or 'skipped' for runs with at least one skipped step. Repeat for multiple."
        ),
    ),
    created_from: datetime | None = Query(
        None,
        description="Include runs created at or after this time (ISO 8601).",
    ),
    created_to: datetime | None = Query(
        None,
        description="Include runs created at or before this time (ISO 8601).",
    ),
    current_user: User = Depends(get_current_user),
    service: RunService = Depends(_service),
) -> WorkflowRunListResponse:
    return service.list_runs(
        workflow_id=workflow_id,
        user_id=current_user.id,
        statuses=status,
        created_from=created_from,
        created_to=created_to,
    )


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
async def get_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    service: RunService = Depends(_service),
) -> WorkflowRunResponse:
    return service.get_run(run_id=run_id, user_id=current_user.id)


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunResponse)
async def cancel_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    service: RunService = Depends(_service),
) -> WorkflowRunResponse:
    return service.cancel_run(run_id=run_id, user_id=current_user.id)
