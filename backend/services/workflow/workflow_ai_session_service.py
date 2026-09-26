from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError, NotFoundError
from core.models.workflow_ai_session import WorkflowAiSession
from models.workflow_ai_session import WorkflowAiSessionResponse
from repositories.user_repository import UserRepository
from repositories.workflow_ai_session_repository import WorkflowAiSessionRepository
from repositories.workflow_repository import WorkflowRepository

logger = logging.getLogger(__name__)


class WorkflowAiSessionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = WorkflowAiSessionRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.user_repo = UserRepository(db)

    def _assert_workflow_access(self, workflow_id: int, user_id: int) -> None:
        # Strict ownership, regardless of visibility — deliberately stricter
        # than BackgroundTierService's private-only check. Enabling an AI
        # session grants ai-assistant write access to the workflow (via
        # WorkflowService.update_workflow_for_ai_session, which skips the
        # normal ownership check entirely and trusts this one instead); on a
        # *public* workflow, any workflows:write holder is not the same as
        # the person entitled to authorize that on the owner's behalf.
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = wf_result
        if workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")

    def _to_response(
        self, workflow_id: int, row: WorkflowAiSession | None
    ) -> WorkflowAiSessionResponse:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = wf_result

        enabled_by_username = None
        if row is not None and row.enabled_by_id is not None:
            enabled_by_user = self.user_repo.get_by_id(row.enabled_by_id)
            enabled_by_username = enabled_by_user.username if enabled_by_user else None

        return WorkflowAiSessionResponse(
            active=row is not None,
            expires_at=row.expires_at if row is not None else None,
            enabled_by_username=enabled_by_username,
            workflow_updated_at=workflow.updated_at,
        )

    def get_status(self, workflow_id: int, user_id: int) -> WorkflowAiSessionResponse:
        self._assert_workflow_access(workflow_id, user_id)
        row = self.repo.get_active_for_workflow(workflow_id)
        return self._to_response(workflow_id, row)

    def enable(
        self, workflow_id: int, user_id: int, ttl_minutes: int
    ) -> WorkflowAiSessionResponse:
        self._assert_workflow_access(workflow_id, user_id)
        expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        row = self.repo.create(workflow_id, enabled_by_id=user_id, expires_at=expires_at)
        logger.info(
            "Enabled AI updates workflow_id=%s user_id=%s expires_at=%s",
            workflow_id,
            user_id,
            expires_at,
        )
        return self._to_response(workflow_id, row)

    def disable(self, workflow_id: int, user_id: int) -> None:
        self._assert_workflow_access(workflow_id, user_id)
        self.repo.expire_active_for_workflow(workflow_id)
        logger.info("Disabled AI updates workflow_id=%s user_id=%s", workflow_id, user_id)
