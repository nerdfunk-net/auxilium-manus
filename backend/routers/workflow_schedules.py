from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.schedules import WorkflowScheduleResponse, WorkflowScheduleUpsert
from services.execution.schedule_service import ScheduleService

router = APIRouter(
    tags=["workflow-schedules"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> ScheduleService:
    return ScheduleService(db)


@router.get(
    "/workflows/{workflow_id}/schedule",
    response_model=WorkflowScheduleResponse | None,
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def get_schedule(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> WorkflowScheduleResponse | None:
    return service.get_schedule(workflow_id=workflow_id, user_id=current_user.id)


@router.put(
    "/workflows/{workflow_id}/schedule",
    response_model=WorkflowScheduleResponse,
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def upsert_schedule(
    workflow_id: int,
    body: WorkflowScheduleUpsert,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> WorkflowScheduleResponse:
    return service.upsert_schedule(workflow_id=workflow_id, data=body, user_id=current_user.id)


@router.delete(
    "/workflows/{workflow_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def delete_schedule(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> None:
    service.delete_schedule(workflow_id=workflow_id, user_id=current_user.id)
