from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.workflows import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowResponse,
    WorkflowUpdate,
)
from services.workflow.workflow_service import WorkflowService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> WorkflowService:
    return WorkflowService(db)


@router.get(
    "",
    response_model=WorkflowListResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
async def list_workflows(
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowListResponse:
    return service.list_workflows(user_id=current_user.id)


@router.get(
    "/check-name",
    response_model=WorkflowNameCheckResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
async def check_workflow_name(
    name: str = Query(..., min_length=1, max_length=255),
    folder: str = Query("/", max_length=500),
    visibility: str = Query("private"),
    exclude_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowNameCheckResponse:
    return service.check_name_available(
        name=name,
        folder=folder,
        visibility=visibility,
        user_id=current_user.id,
        exclude_id=exclude_id,
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
async def get_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowResponse:
    return service.get_workflow(workflow_id=workflow_id, user_id=current_user.id)


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
async def create_workflow(
    body: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowResponse:
    return service.create_workflow(data=body, user_id=current_user.id)


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
async def update_workflow(
    workflow_id: int,
    body: WorkflowUpdate,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowResponse:
    return service.update_workflow(workflow_id=workflow_id, data=body, user_id=current_user.id)


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("workflows", "delete"))],
)
async def delete_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> None:
    service.delete_workflow(workflow_id=workflow_id, user_id=current_user.id)
