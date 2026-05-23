from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.workflows import Workflow
from models.workflows import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowResponse,
    WorkflowSummary,
    WorkflowUpdate,
)
from repositories.workflow_repository import WorkflowRepository

logger = logging.getLogger(__name__)


def _to_summary(workflow: Workflow, creator_username: str | None) -> WorkflowSummary:
    return WorkflowSummary(
        id=workflow.id,
        uuid=workflow.uuid,
        name=workflow.name,
        creator_id=workflow.creator_id,
        creator_username=creator_username,
        description=workflow.description,
        folder=workflow.folder,
        visibility=workflow.visibility,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _to_response(workflow: Workflow, creator_username: str | None) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        uuid=workflow.uuid,
        name=workflow.name,
        creator_id=workflow.creator_id,
        creator_username=creator_username,
        description=workflow.description,
        folder=workflow.folder,
        visibility=workflow.visibility,
        canvas_nodes=workflow.canvas_nodes,
        canvas_edges=workflow.canvas_edges,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


class WorkflowService:
    def __init__(self, db: Session) -> None:
        self.repo = WorkflowRepository(db)

    def list_workflows(self, user_id: int) -> WorkflowListResponse:
        logger.debug("Listing accessible workflows user_id=%s", user_id)
        rows = self.repo.list_accessible(user_id)
        summaries = [_to_summary(wf, username) for wf, username in rows]
        logger.debug("Listed accessible workflows user_id=%s total=%s", user_id, len(summaries))
        return WorkflowListResponse(workflows=summaries, total=len(summaries))

    def get_workflow(self, workflow_id: int, user_id: int) -> WorkflowResponse:
        logger.debug("Getting workflow id=%s user_id=%s", workflow_id, user_id)
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        workflow, creator_username = result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return _to_response(workflow, creator_username)

    def create_workflow(self, data: WorkflowCreate, user_id: int) -> WorkflowResponse:
        logger.info("Creating workflow name=%r user_id=%s", data.name, user_id)
        try:
            workflow = self.repo.create(
                name=data.name,
                creator_id=user_id,
                description=data.description,
                folder=data.folder,
                visibility=data.visibility,
                canvas_nodes=data.canvas_nodes,
                canvas_edges=data.canvas_edges,
            )
            result = self.repo.get_by_id(workflow.id)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Workflow created but could not be retrieved",
                )
            wf, creator_username = result
            logger.info("Workflow created id=%s name=%r user_id=%s", wf.id, wf.name, user_id)
            return _to_response(wf, creator_username)
        except HTTPException:
            raise
        except Exception:
            logger.info(
                "Failed to create workflow name=%r user_id=%s", data.name, user_id, exc_info=True
            )
            raise

    def update_workflow(
        self, workflow_id: int, data: WorkflowUpdate, user_id: int
    ) -> WorkflowResponse:
        logger.info("Updating workflow id=%s user_id=%s", workflow_id, user_id)
        try:
            result = self.repo.get_by_id(workflow_id)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
                )
            workflow, creator_username = result
            if workflow.creator_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            updated_fields = data.model_dump(exclude_unset=True)
            workflow = self.repo.update(workflow, updated_fields)
            logger.info("Workflow updated id=%s user_id=%s", workflow_id, user_id)
            return _to_response(workflow, creator_username)
        except HTTPException:
            raise
        except Exception:
            logger.info(
                "Failed to update workflow id=%s user_id=%s", workflow_id, user_id, exc_info=True
            )
            raise

    def check_name_available(
        self,
        *,
        name: str,
        folder: str,
        visibility: str,
        user_id: int,
        exclude_id: int | None = None,
    ) -> WorkflowNameCheckResponse:
        exists = self.repo.name_exists(
            name=name,
            folder=folder or "/",
            visibility=visibility,
            creator_id=user_id,
            exclude_id=exclude_id,
        )
        if not exists:
            return WorkflowNameCheckResponse(available=True)
        if visibility == "public":
            msg = f'A public workflow named "{name}" already exists in folder "{folder or "/"}".'
        else:
            msg = f'You already have a private workflow named "{name}" in folder "{folder or "/"}".'
        return WorkflowNameCheckResponse(available=False, message=msg)

    def delete_workflow(self, workflow_id: int, user_id: int) -> None:
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        workflow, _ = result
        if workflow.creator_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        self.repo.delete(workflow)
