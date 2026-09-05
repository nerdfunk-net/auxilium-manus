from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.domain_exceptions import DomainError
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.workflow_changes import WorkflowChangeListResponse
from models.workflows import (
    WorkflowCreate,
    WorkflowGitDiffRequest,
    WorkflowGitDiffResponse,
    WorkflowGitHistoryResponse,
    WorkflowGitRestoreRequest,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowNotesResponse,
    WorkflowNotesUpdate,
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
def list_workflows(
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowListResponse:
    return service.list_workflows(user_id=current_user.id)


@router.get(
    "/check-name",
    response_model=WorkflowNameCheckResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
def check_workflow_name(
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
def get_workflow(
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
def create_workflow(
    body: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowResponse:
    try:
        return service.create_workflow(
            data=body, user_id=current_user.id, actor_username=current_user.username
        )
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create workflow", exc)


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
def update_workflow(
    workflow_id: int,
    body: WorkflowUpdate,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowResponse:
    try:
        return service.update_workflow(
            workflow_id=workflow_id,
            data=body,
            user_id=current_user.id,
            actor_username=current_user.username,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update workflow", exc)


@router.get(
    "/{workflow_id}/changes",
    response_model=WorkflowChangeListResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
def get_workflow_changes(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowChangeListResponse:
    try:
        return service.get_workflow_changes(workflow_id=workflow_id, user_id=current_user.id)
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get workflow changes", exc)


@router.patch(
    "/{workflow_id}/notes",
    response_model=WorkflowNotesResponse,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
def update_workflow_notes(
    workflow_id: int,
    body: WorkflowNotesUpdate,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowNotesResponse:
    try:
        return service.update_notes(
            workflow_id=workflow_id, user_id=current_user.id, notes=body.notes
        )
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update workflow notes", exc)


@router.get(
    "/{workflow_id}/version-control/history",
    response_model=WorkflowGitHistoryResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
def get_workflow_git_history(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowGitHistoryResponse:
    try:
        return service.get_workflow_git_history(workflow_id=workflow_id, user_id=current_user.id)
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get workflow git history", exc)


@router.post(
    "/{workflow_id}/version-control/diff",
    response_model=WorkflowGitDiffResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
def diff_workflow_git_versions(
    workflow_id: int,
    body: WorkflowGitDiffRequest,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowGitDiffResponse:
    try:
        return service.get_workflow_git_diff(
            workflow_id=workflow_id,
            commit_a=body.commit_a,
            commit_b=body.commit_b,
            user_id=current_user.id,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to diff workflow git versions", exc)


@router.post(
    "/{workflow_id}/version-control/restore",
    response_model=WorkflowResponse,
    dependencies=[Depends(require_permission("workflows", "write"))],
)
def restore_workflow_git_version(
    workflow_id: int,
    body: WorkflowGitRestoreRequest,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> WorkflowResponse:
    try:
        return service.restore_workflow_version(
            workflow_id=workflow_id,
            commit_sha=body.commit_sha,
            user_id=current_user.id,
            actor_username=current_user.username,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to restore workflow git version", exc)


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("workflows", "delete"))],
)
def delete_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: WorkflowService = Depends(_service),
) -> None:
    try:
        service.delete_workflow(workflow_id=workflow_id, user_id=current_user.id)
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete workflow", exc)
