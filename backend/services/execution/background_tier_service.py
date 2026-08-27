from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError, NotFoundError
from core.models.background_tier import WorkflowBackgroundTier
from models.background_tier import BackgroundTierResponse, BackgroundTierUpsert
from repositories.background_tier_repository import BackgroundTierRepository
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository

logger = logging.getLogger(__name__)

# Mirrors RunService.cancel_run's own non-terminal check — used only to decide
# whether to warn on unpublish, not to block it.
_NON_TERMINAL_RUN_STATUSES = ("pending", "running", "paused")


def _to_response(row: WorkflowBackgroundTier) -> BackgroundTierResponse:
    return BackgroundTierResponse(
        id=row.id,
        uuid=row.uuid,
        workflow_id=row.workflow_id,
        hatchet_workflow_name=row.hatchet_workflow_name,
        concurrency_limit=row.concurrency_limit,
        published_by_id=row.published_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class BackgroundTierService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = BackgroundTierRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.run_repo = RunRepository(db)

    def _assert_workflow_access(self, workflow_id: int, user_id: int) -> None:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = wf_result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")

    def get_status(self, workflow_id: int, user_id: int) -> BackgroundTierResponse | None:
        self._assert_workflow_access(workflow_id, user_id)
        row = self.repo.get_by_workflow_id(workflow_id)
        return _to_response(row) if row else None

    def publish(
        self, workflow_id: int, data: BackgroundTierUpsert, user_id: int
    ) -> BackgroundTierResponse:
        self._assert_workflow_access(workflow_id, user_id)
        row = self.repo.publish(
            workflow_id,
            concurrency_limit=data.concurrency_limit,
            published_by_id=user_id,
        )
        logger.info(
            "Published workflow_id=%s hatchet_workflow_name=%s concurrency_limit=%s user_id=%s",
            workflow_id,
            row.hatchet_workflow_name,
            row.concurrency_limit,
            user_id,
        )
        return _to_response(row)

    def has_active_runs(self, workflow_id: int) -> bool:
        runs = self.run_repo.list_runs_for_workflow(
            workflow_id, statuses=list(_NON_TERMINAL_RUN_STATUSES)
        )
        return len(runs) > 0

    def unpublish(self, workflow_id: int, user_id: int) -> None:
        self._assert_workflow_access(workflow_id, user_id)
        row = self.repo.get_by_workflow_id(workflow_id)
        if row is None:
            raise NotFoundError("Workflow is not published")
        self.repo.unpublish(row)
        logger.info("Unpublished workflow_id=%s user_id=%s", workflow_id, user_id)

    def unpublish_for_workflow_unchecked(self, workflow_id: int) -> None:
        """Mirrors ScheduleService.delete_schedule_for_workflow_unchecked — called
        from WorkflowService.delete_workflow, where ownership was already verified."""
        row = self.repo.get_by_workflow_id(workflow_id)
        if row is None:
            return
        self.repo.unpublish(row)
