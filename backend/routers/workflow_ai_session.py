from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.workflow_ai_session import WorkflowAiSessionEnableRequest, WorkflowAiSessionResponse
from services.workflow.workflow_ai_session_service import WorkflowAiSessionService

router = APIRouter(
    tags=["workflow-ai-session"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> WorkflowAiSessionService:
    return WorkflowAiSessionService(db)


@router.get(
    "/workflows/{workflow_id}/ai-session",
    response_model=WorkflowAiSessionResponse,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
def get_ai_session(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowAiSessionService = Depends(_service),
) -> WorkflowAiSessionResponse:
    return service.get_status(workflow_id=workflow_id, user_id=current_user.id)


@router.put(
    "/workflows/{workflow_id}/ai-session",
    response_model=WorkflowAiSessionResponse,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
def enable_ai_session(
    workflow_id: int,
    body: WorkflowAiSessionEnableRequest,
    current_user: User = Depends(get_current_user),
    service: WorkflowAiSessionService = Depends(_service),
) -> WorkflowAiSessionResponse:
    return service.enable(
        workflow_id=workflow_id, user_id=current_user.id, ttl_minutes=body.ttl_minutes
    )


@router.delete(
    "/workflows/{workflow_id}/ai-session",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
def disable_ai_session(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowAiSessionService = Depends(_service),
) -> None:
    service.disable(workflow_id=workflow_id, user_id=current_user.id)
