from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.artifacts import ArtifactContentResponse
from models.change_requests import (
    ChangeRequestApproveRequest,
    ChangeRequestListResponse,
    ChangeRequestRejectRequest,
    ChangeRequestResponse,
)
from services.change_requests.change_request_service import ChangeRequestService

router = APIRouter(
    tags=["change-requests"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> ChangeRequestService:
    return ChangeRequestService(db)


@router.get(
    "/change-requests",
    response_model=ChangeRequestListResponse,
    dependencies=[Depends(require_permission("change_requests", "read"))],
)
def list_change_requests(
    status_filter: list[str] | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    service: ChangeRequestService = Depends(_service),
) -> ChangeRequestListResponse:
    return service.list(current_user.id, statuses=status_filter)


@router.get(
    "/change-requests/{change_request_id}",
    response_model=ChangeRequestResponse,
    dependencies=[Depends(require_permission("change_requests", "read"))],
)
def get_change_request(
    change_request_id: int,
    current_user: User = Depends(get_current_user),
    service: ChangeRequestService = Depends(_service),
) -> ChangeRequestResponse:
    return service.get(change_request_id, current_user.id)


@router.get(
    "/change-requests/{change_request_id}/diff",
    response_model=ArtifactContentResponse,
    dependencies=[Depends(require_permission("change_requests", "read"))],
)
def get_change_request_diff(
    change_request_id: int,
    current_user: User = Depends(get_current_user),
    service: ChangeRequestService = Depends(_service),
) -> ArtifactContentResponse:
    return service.get_diff(change_request_id, current_user.id)


@router.post(
    "/change-requests/{change_request_id}/approve",
    response_model=ChangeRequestResponse,
    dependencies=[Depends(require_permission("change_requests", "approve"))],
)
def approve_change_request(
    change_request_id: int,
    body: ChangeRequestApproveRequest | None = None,
    current_user: User = Depends(get_current_user),
    service: ChangeRequestService = Depends(_service),
) -> ChangeRequestResponse:
    payload = body or ChangeRequestApproveRequest()
    return service.approve(
        change_request_id,
        actor_user_id=current_user.id,
        via="ui",
        deploy_workflow_id=payload.deploy_workflow_id,
    )


@router.post(
    "/change-requests/{change_request_id}/deploy",
    response_model=ChangeRequestResponse,
    dependencies=[Depends(require_permission("change_requests", "approve"))],
)
def deploy_change_request(
    change_request_id: int,
    body: ChangeRequestApproveRequest | None = None,
    current_user: User = Depends(get_current_user),
    service: ChangeRequestService = Depends(_service),
) -> ChangeRequestResponse:
    payload = body or ChangeRequestApproveRequest()
    return service.deploy(
        change_request_id,
        actor_user_id=current_user.id,
        deploy_workflow_id=payload.deploy_workflow_id,
    )


@router.post(
    "/change-requests/{change_request_id}/reject",
    response_model=ChangeRequestResponse,
    dependencies=[Depends(require_permission("change_requests", "approve"))],
)
def reject_change_request(
    change_request_id: int,
    body: ChangeRequestRejectRequest | None = None,
    current_user: User = Depends(get_current_user),
    service: ChangeRequestService = Depends(_service),
) -> ChangeRequestResponse:
    payload = body or ChangeRequestRejectRequest()
    return service.reject(
        change_request_id, actor_user_id=current_user.id, reason=payload.reason
    )
