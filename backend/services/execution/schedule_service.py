from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from core.models.schedules import WorkflowSchedule
from core.safe_http_errors import raise_internal_server_error
from hatchet.client import hatchet
from models.schedules import WorkflowScheduleResponse, WorkflowScheduleUpsert
from repositories.schedule_repository import ScheduleRepository
from repositories.workflow_repository import WorkflowRepository

logger = logging.getLogger(__name__)

_TARGET_WORKFLOW_NAME = "ScheduledWorkflowTrigger"


def _to_response(schedule: WorkflowSchedule) -> WorkflowScheduleResponse:
    return WorkflowScheduleResponse(
        id=schedule.id,
        uuid=schedule.uuid,
        workflow_id=schedule.workflow_id,
        schedule_type=schedule.schedule_type,
        cron_expression=schedule.cron_expression,
        run_at=schedule.run_at,
        enabled=schedule.enabled,
        last_triggered_at=schedule.last_triggered_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


class ScheduleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ScheduleRepository(db)
        self.wf_repo = WorkflowRepository(db)

    def _assert_workflow_access(self, workflow_id: int, user_id: int) -> None:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        workflow, _ = wf_result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    def _delete_hatchet_entry(self, schedule: WorkflowSchedule) -> None:
        try:
            if schedule.hatchet_cron_id:
                hatchet.cron.delete(schedule.hatchet_cron_id)
            if schedule.hatchet_scheduled_id:
                hatchet.scheduled.delete(schedule.hatchet_scheduled_id)
        except Exception as exc:
            raise_internal_server_error(
                logger,
                f"Failed to remove Hatchet schedule for workflow_id={schedule.workflow_id}",
                exc,
            )

    def get_schedule(self, workflow_id: int, user_id: int) -> WorkflowScheduleResponse | None:
        self._assert_workflow_access(workflow_id, user_id)
        schedule = self.repo.get_by_workflow_id(workflow_id)
        return _to_response(schedule) if schedule else None

    def upsert_schedule(
        self, workflow_id: int, data: WorkflowScheduleUpsert, user_id: int
    ) -> WorkflowScheduleResponse:
        self._assert_workflow_access(workflow_id, user_id)

        if data.schedule_type == "cron":
            if not data.cron_expression:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="cron_expression is required for a recurring schedule",
                )
        else:
            if data.run_at is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="run_at is required for a one-time schedule",
                )
            if data.run_at <= datetime.now(UTC):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="run_at must be in the future",
                )

        existing = self.repo.get_by_workflow_id(workflow_id)
        if existing is not None and (existing.hatchet_cron_id or existing.hatchet_scheduled_id):
            self._delete_hatchet_entry(existing)

        schedule = self.repo.upsert(
            workflow_id,
            created_by_id=user_id,
            schedule_type=data.schedule_type,
            cron_expression=data.cron_expression,
            run_at=data.run_at,
            enabled=data.enabled,
        )

        if data.enabled:
            trigger_input = {"workflow_id": workflow_id, "schedule_id": schedule.id}
            try:
                if data.schedule_type == "cron":
                    result = hatchet.cron.create(
                        workflow_name=_TARGET_WORKFLOW_NAME,
                        cron_name=f"workflow-{workflow_id}",
                        expression=data.cron_expression or "",
                        input=trigger_input,
                        additional_metadata={"workflow_id": workflow_id},
                    )
                    self.repo.set_hatchet_ids(schedule, hatchet_cron_id=str(result.metadata.id))
                else:
                    result = hatchet.scheduled.create(
                        workflow_name=_TARGET_WORKFLOW_NAME,
                        trigger_at=data.run_at,
                        input=trigger_input,
                        additional_metadata={"workflow_id": workflow_id},
                    )
                    self.repo.set_hatchet_ids(
                        schedule, hatchet_scheduled_id=str(result.metadata.id)
                    )
            except ValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid schedule configuration: {exc}",
                ) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise_internal_server_error(
                    logger,
                    f"Failed to register Hatchet schedule for workflow_id={workflow_id}",
                    exc,
                )

        logger.info(
            "Upserted schedule workflow_id=%s schedule_id=%s type=%s enabled=%s",
            workflow_id,
            schedule.id,
            schedule.schedule_type,
            schedule.enabled,
        )
        return _to_response(schedule)

    def delete_schedule(self, workflow_id: int, user_id: int) -> None:
        self._assert_workflow_access(workflow_id, user_id)
        schedule = self.repo.get_by_workflow_id(workflow_id)
        if schedule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
        self._delete_hatchet_entry(schedule)
        self.repo.delete(schedule)
        logger.info("Deleted schedule workflow_id=%s user_id=%s", workflow_id, user_id)

    def delete_schedule_for_workflow_unchecked(self, workflow_id: int) -> None:
        """Clean up a workflow's schedule without an access check.

        Used from WorkflowService.delete_workflow, where ownership was already
        verified — without this, deleting a workflow would leave its Hatchet
        cron/scheduled entry dangling and firing into an orphaned lookup.
        """
        schedule = self.repo.get_by_workflow_id(workflow_id)
        if schedule is None:
            return
        self._delete_hatchet_entry(schedule)
        self.repo.delete(schedule)
