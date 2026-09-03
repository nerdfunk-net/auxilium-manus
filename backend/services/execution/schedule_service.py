from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from hatchet_sdk.clients.rest.exceptions import NotFoundException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from core.domain_exceptions import (
    AccessDeniedError,
    DomainError,
    NotFoundError,
    ValidationFailedError,
)
from core.models.schedules import WorkflowSchedule
from core.models.workflows import Workflow
from core.safe_http_errors import raise_internal_server_error
from hatchet.client import hatchet
from models.background_tier import BackgroundTierUpsert
from models.schedules import (
    WorkflowScheduleCreate,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdate,
)
from repositories.background_tier_repository import BackgroundTierRepository
from repositories.schedule_repository import ScheduleRepository
from repositories.workflow_repository import WorkflowRepository
from services.execution.background_tier_service import BackgroundTierService
from services.execution.reference_resolver import (
    ReferenceValidationError,
    validate_reference_inputs,
)
from services.execution.run_input_validation import (
    RunInputValidationError,
    resolve_run_inputs,
)

logger = logging.getLogger(__name__)

_TARGET_WORKFLOW_NAME = "ScheduledWorkflowTrigger"


class ScheduleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ScheduleRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.tier_repo = BackgroundTierRepository(db)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _load_workflow(self, workflow_id: int, user_id: int) -> Workflow:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = wf_result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        return workflow

    def _to_response(self, schedule: WorkflowSchedule) -> WorkflowScheduleResponse:
        wf_result = self.wf_repo.get_by_id(schedule.workflow_id)
        workflow_name = wf_result[0].name if wf_result else None
        tier = self.tier_repo.get_by_workflow_id(schedule.workflow_id)
        return WorkflowScheduleResponse(
            id=schedule.id,
            uuid=schedule.uuid,
            workflow_id=schedule.workflow_id,
            workflow_name=workflow_name,
            name=schedule.name,
            schedule_type=schedule.schedule_type,
            cron_expression=schedule.cron_expression,
            run_at=schedule.run_at,
            enabled=schedule.enabled,
            run_inputs=schedule.run_inputs or {},
            concurrency_limit=tier.concurrency_limit if tier else None,
            last_triggered_at=schedule.last_triggered_at,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )

    def _resolve_run_inputs(
        self, workflow: Workflow, supplied: dict[str, Any], acting_user_id: int
    ) -> dict[str, Any]:
        """Shape-validate against static_attributes, then check every
        `reference` value resolves for the schedule owner. Raises
        ValidationFailedError (→ 422) on any problem."""
        try:
            resolved = resolve_run_inputs(workflow.static_attributes, supplied)
        except RunInputValidationError as exc:
            raise ValidationFailedError(str(exc)) from exc
        try:
            validate_reference_inputs(
                workflow.static_attributes,
                resolved,
                db=self.db,
                acting_user_id=acting_user_id,
            )
        except ReferenceValidationError as exc:
            raise ValidationFailedError(str(exc)) from exc
        return resolved

    @staticmethod
    def _validate_timing(
        schedule_type: str, cron_expression: str | None, run_at: datetime | None
    ) -> None:
        if schedule_type == "cron":
            if not cron_expression:
                raise ValidationFailedError(
                    "cron_expression is required for a recurring schedule"
                )
        else:
            if run_at is None:
                raise ValidationFailedError("run_at is required for a one-time schedule")
            if run_at <= datetime.now(UTC):
                raise ValidationFailedError("run_at must be in the future")

    def _delete_hatchet_entry(self, schedule: WorkflowSchedule) -> None:
        """Best-effort removal of the schedule's Hatchet cron/scheduled entry.

        A 404 means Hatchet already has no such entry — a consumed one-time
        trigger, an entry lost across a Hatchet restart, or a double delete.
        That is the desired end state, so it is logged and ignored; only an
        unexpected failure is surfaced as a 5xx.
        """
        try:
            if schedule.hatchet_cron_id:
                hatchet.cron.delete(schedule.hatchet_cron_id)
            if schedule.hatchet_scheduled_id:
                hatchet.scheduled.delete(schedule.hatchet_scheduled_id)
        except NotFoundException:
            logger.info(
                "Hatchet schedule entry already gone for schedule_id=%s workflow_id=%s "
                "(cron_id=%s scheduled_id=%s) — nothing to remove",
                schedule.id,
                schedule.workflow_id,
                schedule.hatchet_cron_id,
                schedule.hatchet_scheduled_id,
            )
        except Exception as exc:
            raise_internal_server_error(
                logger,
                f"Failed to remove Hatchet schedule for workflow_id={schedule.workflow_id}",
                exc,
            )

    def _register_hatchet_entry(self, schedule: WorkflowSchedule) -> None:
        if not schedule.enabled:
            return
        trigger_input = {
            "workflow_id": schedule.workflow_id,
            "schedule_id": schedule.id,
        }
        try:
            if schedule.schedule_type == "cron":
                result = hatchet.cron.create(
                    workflow_name=_TARGET_WORKFLOW_NAME,
                    cron_name=f"workflow-{schedule.workflow_id}-schedule-{schedule.id}",
                    expression=schedule.cron_expression or "",
                    input=trigger_input,
                    additional_metadata={"workflow_id": schedule.workflow_id},
                )
                self.repo.set_hatchet_ids(schedule, hatchet_cron_id=str(result.metadata.id))
            else:
                result = hatchet.scheduled.create(
                    workflow_name=_TARGET_WORKFLOW_NAME,
                    trigger_at=schedule.run_at,
                    input=trigger_input,
                    additional_metadata={"workflow_id": schedule.workflow_id},
                )
                self.repo.set_hatchet_ids(
                    schedule, hatchet_scheduled_id=str(result.metadata.id)
                )
        except ValidationError as exc:
            raise ValidationFailedError(f"Invalid schedule configuration: {exc}") from exc
        except DomainError:
            raise
        except Exception as exc:
            raise_internal_server_error(
                logger,
                f"Failed to register Hatchet schedule for workflow_id={schedule.workflow_id}",
                exc,
            )

    def _ensure_published(
        self, workflow_id: int, concurrency_limit: int | None, user_id: int
    ) -> None:
        """A scheduled workflow always runs on the background tier so overlapping
        fires are serialised by Hatchet's own concurrency limit rather than each
        opening its own device fan-out."""
        BackgroundTierService(self.db).publish(
            workflow_id,
            BackgroundTierUpsert(concurrency_limit=concurrency_limit),
            user_id,
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def list_schedules(
        self, user_id: int, workflow_id: int | None = None
    ) -> list[WorkflowScheduleResponse]:
        rows = self.repo.list_visible(user_id, workflow_id=workflow_id)
        tiers = {
            wf_id: self.tier_repo.get_by_workflow_id(wf_id)
            for wf_id in {schedule.workflow_id for schedule, _ in rows}
        }
        return [
            WorkflowScheduleResponse(
                id=schedule.id,
                uuid=schedule.uuid,
                workflow_id=schedule.workflow_id,
                workflow_name=workflow_name,
                name=schedule.name,
                schedule_type=schedule.schedule_type,
                cron_expression=schedule.cron_expression,
                run_at=schedule.run_at,
                enabled=schedule.enabled,
                run_inputs=schedule.run_inputs or {},
                concurrency_limit=(
                    tiers[schedule.workflow_id].concurrency_limit
                    if tiers.get(schedule.workflow_id)
                    else None
                ),
                last_triggered_at=schedule.last_triggered_at,
                created_at=schedule.created_at,
                updated_at=schedule.updated_at,
            )
            for schedule, workflow_name in rows
        ]

    def get_schedule(self, schedule_id: int, user_id: int) -> WorkflowScheduleResponse:
        schedule = self.repo.get_by_id(schedule_id)
        if schedule is None:
            raise NotFoundError("Schedule not found")
        self._load_workflow(schedule.workflow_id, user_id)
        return self._to_response(schedule)

    def create_schedule(
        self, data: WorkflowScheduleCreate, user_id: int
    ) -> WorkflowScheduleResponse:
        workflow = self._load_workflow(data.workflow_id, user_id)
        self._validate_timing(data.schedule_type, data.cron_expression, data.run_at)
        run_inputs = self._resolve_run_inputs(workflow, data.run_inputs, user_id)

        self._ensure_published(data.workflow_id, data.concurrency_limit, user_id)

        schedule = self.repo.create(
            data.workflow_id,
            created_by_id=user_id,
            name=data.name,
            schedule_type=data.schedule_type,
            cron_expression=data.cron_expression,
            run_at=data.run_at,
            enabled=data.enabled,
            run_inputs=run_inputs,
        )
        self._register_hatchet_entry(schedule)
        logger.info(
            "Created schedule id=%s workflow_id=%s type=%s enabled=%s",
            schedule.id,
            schedule.workflow_id,
            schedule.schedule_type,
            schedule.enabled,
        )
        return self._to_response(schedule)

    def update_schedule(
        self, schedule_id: int, data: WorkflowScheduleUpdate, user_id: int
    ) -> WorkflowScheduleResponse:
        schedule = self.repo.get_by_id(schedule_id)
        if schedule is None:
            raise NotFoundError("Schedule not found")
        workflow = self._load_workflow(schedule.workflow_id, user_id)

        schedule_type = data.schedule_type or schedule.schedule_type
        cron_expression = (
            data.cron_expression
            if data.cron_expression is not None
            else schedule.cron_expression
        )
        run_at = data.run_at if data.run_at is not None else schedule.run_at
        enabled = data.enabled if data.enabled is not None else schedule.enabled
        self._validate_timing(schedule_type, cron_expression, run_at)

        run_inputs = schedule.run_inputs or {}
        if data.run_inputs is not None:
            run_inputs = self._resolve_run_inputs(workflow, data.run_inputs, user_id)

        if data.concurrency_limit is not None:
            self._ensure_published(schedule.workflow_id, data.concurrency_limit, user_id)

        if schedule.hatchet_cron_id or schedule.hatchet_scheduled_id:
            self._delete_hatchet_entry(schedule)

        schedule = self.repo.update(
            schedule,
            name=data.name if data.name is not None else schedule.name,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            run_at=run_at,
            enabled=enabled,
            run_inputs=run_inputs,
        )
        self._register_hatchet_entry(schedule)
        logger.info("Updated schedule id=%s workflow_id=%s", schedule.id, schedule.workflow_id)
        return self._to_response(schedule)

    def delete_schedule(self, schedule_id: int, user_id: int) -> None:
        schedule = self.repo.get_by_id(schedule_id)
        if schedule is None:
            raise NotFoundError("Schedule not found")
        self._load_workflow(schedule.workflow_id, user_id)
        self._delete_hatchet_entry(schedule)
        self.repo.delete(schedule)
        logger.info("Deleted schedule id=%s user_id=%s", schedule_id, user_id)

    def delete_schedules_for_workflow_unchecked(self, workflow_id: int) -> None:
        """Remove every schedule for a workflow without an access check — used
        from WorkflowService.delete_workflow where ownership is already verified.
        Without this, deleting a workflow would leave Hatchet cron/scheduled
        entries firing into an orphaned lookup."""
        for schedule in self.repo.list_by_workflow_id(workflow_id):
            self._delete_hatchet_entry(schedule)
            self.repo.delete(schedule)
