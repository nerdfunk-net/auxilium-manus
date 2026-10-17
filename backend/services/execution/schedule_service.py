from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from hatchet_sdk.clients.rest.exceptions import (
    NotFoundException,
    RestTransportError,
    ServiceException,
)
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
    ScheduleType,
    WorkflowScheduleCreate,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdate,
)
from repositories.background_tier_repository import BackgroundTierRepository
from repositories.schedule_repository import ScheduleRepository
from repositories.workflow_repository import WorkflowRepository
from services.execution.background_tier_service import BackgroundTierService
from services.execution.dispatch_breaker import ENGINE_UNAVAILABLE_MESSAGE
from services.execution.reference_resolver import (
    ReferenceValidationError,
    validate_reference_inputs,
)
from services.execution.run_input_validation import (
    RunInputValidationError,
    resolve_run_inputs,
)
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, redact_secrets_in_data

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

    def _assert_schedule_owner(self, schedule: WorkflowSchedule, user_id: int) -> None:
        """Only the creator edits or deletes a schedule (S2-05); an administrator may as an
        audited exception."""
        if schedule.created_by_id == user_id:
            return
        from services.auth.rbac_service import RBACService

        if RBACService(self.db).has_role(user_id, "admin"):
            logger.warning(
                "schedule_admin_override user_id=%s schedule_id=%s", user_id, schedule.id
            )
            return
        raise AccessDeniedError("Only the creator of a schedule can change or delete it")

    def disable_for_user(self, user_id: int) -> int:
        """A deactivated user's schedules stop firing (S2-04). Reactivation does not re-enable."""
        count = 0
        for schedule in self.repo.list_by_creator(user_id):
            self._delete_hatchet_entry(schedule)
            self.repo.update(schedule, enabled=False)
            count += 1
        return count

    def delete_for_user(self, user_id: int) -> int:
        """A deleted user's schedules are removed with them (S2-04)."""
        count = 0
        for schedule in self.repo.list_by_creator(user_id):
            self._delete_hatchet_entry(schedule)
            self.repo.delete(schedule)
            count += 1
        return count

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
            schedule_type=cast("ScheduleType", schedule.schedule_type),
            cron_expression=schedule.cron_expression,
            run_at=schedule.run_at,
            enabled=schedule.enabled,
            run_inputs=redact_secrets_in_data(schedule.run_inputs or {}),
            concurrency_limit=tier.concurrency_limit if tier else None,
            last_triggered_at=schedule.last_triggered_at,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )

    @staticmethod
    def _keep_stored_secrets(
        workflow: Workflow, supplied: dict[str, Any], stored: dict[str, Any]
    ) -> dict[str, Any]:
        """API responses show a secret input as the redaction placeholder, so an edit that
        leaves it alone (omitted or echoed back) keeps the sealed value already stored."""
        merged = dict(supplied)
        for raw in workflow.static_attributes or []:
            if raw.get("type") != "secret":
                continue
            name = raw.get("name")
            if (name not in merged or merged[name] == REDACTED_PLACEHOLDER) and name in stored:
                merged[name] = stored[name]
        return merged

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
        self._delete_entry_ids(
            schedule.hatchet_cron_id,
            schedule.hatchet_scheduled_id,
            best_effort=False,
            schedule=schedule,
        )

    def _delete_entry_ids(
        self,
        cron_id: str | None,
        scheduled_id: str | None,
        *,
        best_effort: bool,
        schedule: WorkflowSchedule | None = None,
    ) -> None:
        """Removal of a Hatchet cron/scheduled entry by id.

        A 404 means Hatchet already has no such entry — a consumed one-time
        trigger, an entry lost across a Hatchet restart, or a double delete.
        That is the desired end state, so it is logged and ignored; only an
        unexpected failure is surfaced as a 5xx.
        """
        try:
            if cron_id:
                hatchet.cron.delete(cron_id)
            if scheduled_id:
                hatchet.scheduled.delete(scheduled_id)
        except NotFoundException:
            logger.info(
                "Hatchet schedule entry already gone for schedule_id=%s workflow_id=%s "
                "(cron_id=%s scheduled_id=%s) — nothing to remove",
                schedule.id if schedule else None,
                schedule.workflow_id if schedule else None,
                cron_id,
                scheduled_id,
            )
        except Exception as exc:
            if best_effort:
                # The row no longer points at this entry; a leftover entry is skipped by the
                # trigger (it re-checks the row) and is logged for the operator.
                logger.warning(
                    "Could not remove old Hatchet schedule entry cron_id=%s scheduled_id=%s: %s",
                    cron_id,
                    scheduled_id,
                    type(exc).__name__,
                )
                return
            raise_internal_server_error(
                logger,
                "Failed to remove Hatchet schedule for workflow_id="
                f"{schedule.workflow_id if schedule else None}",
                exc,
            )

    def _register_hatchet_entry(
        self, schedule: WorkflowSchedule, *, name_suffix: str = ""
    ) -> None:
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
                    # An update registers the new entry while the old one still exists, so its
                    # name must differ (Hatchet keeps cron name + expression unique).
                    cron_name=(
                        f"workflow-{schedule.workflow_id}-schedule-{schedule.id}{name_suffix}"
                    ),
                    expression=schedule.cron_expression or "",
                    input=trigger_input,
                    additional_metadata={"workflow_id": schedule.workflow_id},
                )
                self.repo.set_hatchet_ids(schedule, hatchet_cron_id=str(result.metadata.id))
            else:
                if schedule.run_at is None:
                    raise ValidationFailedError("run_at is required for a one-time schedule")
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
        except (RestTransportError, ServiceException) as exc:
            # O4-09: the engine cannot be reached (or answered 5xx): the same 503 and message as a
            # manual trigger gets, not a generic 500.
            raise_internal_server_error(
                logger,
                f"Hatchet unavailable while registering a schedule for "
                f"workflow_id={schedule.workflow_id}",
                exc,
                status_code=503,
                public_message=ENGINE_UNAVAILABLE_MESSAGE,
            )
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

    def _publication_state(self, workflow_id: int) -> tuple[bool, int | None]:
        """Whether the workflow is on the background tier, and its limit, read before a change."""
        tier = self.tier_repo.get_by_workflow_id(workflow_id)
        return (tier is not None, tier.concurrency_limit if tier is not None else None)

    def _undo_publish(
        self,
        workflow_id: int,
        user_id: int,
        before: tuple[bool, int | None],
        requested_limit: int | None,
    ) -> None:
        """Put the background tier back as it was when a schedule change failed after publishing.

        A tier this call created is removed; one that already existed stays, with its previous
        concurrency limit. Best effort: the original error is the one the caller must see."""
        was_published, previous_limit = before
        try:
            tiers = BackgroundTierService(self.db)
            if not was_published:
                tiers.unpublish_for_workflow_unchecked(workflow_id)
            elif previous_limit != requested_limit:
                tiers.publish(
                    workflow_id, BackgroundTierUpsert(concurrency_limit=previous_limit), user_id
                )
        except Exception:
            logger.warning(
                "Could not restore the background tier of workflow_id=%s after a failed schedule "
                "change",
                workflow_id,
                exc_info=True,
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
                schedule_type=cast("ScheduleType", schedule.schedule_type),
                cron_expression=schedule.cron_expression,
                run_at=schedule.run_at,
                enabled=schedule.enabled,
                run_inputs=redact_secrets_in_data(schedule.run_inputs or {}),
                concurrency_limit=(
                    tier.concurrency_limit if (tier := tiers.get(schedule.workflow_id)) else None
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

        tier_before = self._publication_state(data.workflow_id)
        self._ensure_published(data.workflow_id, data.concurrency_limit, user_id)

        try:
            schedule = self.repo.create(
                data.workflow_id,
                created_by_id=user_id,
                name=data.name,
                schedule_type=data.schedule_type,
                cron_expression=data.cron_expression,
                run_at=data.run_at,
                # Stored disabled: a disabled row can never fire (the trigger re-checks
                # ``enabled``), so a registration failure below leaves nothing active behind.
                enabled=False,
                run_inputs=run_inputs,
            )
        except Exception:
            self._undo_publish(data.workflow_id, user_id, tier_before, data.concurrency_limit)
            raise
        try:
            schedule.enabled = data.enabled  # in memory; set_hatchet_ids() commits it with the ids
            self._register_hatchet_entry(schedule)
        except Exception:
            self.db.rollback()
            self.repo.delete(schedule)  # compensate: no half-created schedule remains
            # O4-04: and no workflow left published to the background tier by this attempt.
            self._undo_publish(data.workflow_id, user_id, tier_before, data.concurrency_limit)
            raise
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
        self._assert_schedule_owner(schedule, user_id)

        schedule_type = data.schedule_type or schedule.schedule_type
        cron_expression = (
            data.cron_expression
            if data.cron_expression is not None
            else schedule.cron_expression
        )
        run_at = data.run_at if data.run_at is not None else schedule.run_at
        enabled = data.enabled if data.enabled is not None else schedule.enabled
        # A fired one-time schedule keeps a past run_at: renaming it or changing its inputs must
        # not trip the future-only rule. Timing is validated when it changes or when the
        # schedule becomes active again.
        timing_changed = any(
            value is not None for value in (data.schedule_type, data.cron_expression, data.run_at)
        )
        becoming_active = data.enabled is True and not schedule.enabled
        if timing_changed or becoming_active:
            self._validate_timing(schedule_type, cron_expression, run_at)

        run_inputs = schedule.run_inputs or {}
        if data.run_inputs is not None:
            supplied = self._keep_stored_secrets(
                workflow, data.run_inputs, schedule.run_inputs or {}
            )
            run_inputs = self._resolve_run_inputs(workflow, supplied, user_id)

        tier_before = self._publication_state(schedule.workflow_id)
        if data.concurrency_limit is not None:
            self._ensure_published(schedule.workflow_id, data.concurrency_limit, user_id)

        old_cron_id, old_scheduled_id = schedule.hatchet_cron_id, schedule.hatchet_scheduled_id

        schedule = self.repo.update(
            schedule,
            name=data.name if data.name is not None else schedule.name,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            run_at=run_at,
            enabled=enabled,
            run_inputs=run_inputs,
        )
        try:
            # The new entry first; the old one is removed only after the new one exists.
            self._register_hatchet_entry(schedule, name_suffix=f"-{uuid.uuid4().hex[:8]}")
        except Exception:
            # It cannot fire without an entry, and the list says so.
            self.repo.update(schedule, enabled=False)
            self._delete_entry_ids(old_cron_id, old_scheduled_id, best_effort=True)
            if data.concurrency_limit is not None:  # O4-04: undo only what this call published
                self._undo_publish(
                    schedule.workflow_id, user_id, tier_before, data.concurrency_limit
                )
            raise
        self._delete_entry_ids(old_cron_id, old_scheduled_id, best_effort=True)
        logger.info("Updated schedule id=%s workflow_id=%s", schedule.id, schedule.workflow_id)
        return self._to_response(schedule)

    def delete_schedule(self, schedule_id: int, user_id: int) -> None:
        schedule = self.repo.get_by_id(schedule_id)
        if schedule is None:
            raise NotFoundError("Schedule not found")
        self._load_workflow(schedule.workflow_id, user_id)
        self._assert_schedule_owner(schedule, user_id)
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
