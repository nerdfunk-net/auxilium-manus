from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from core.config import settings
from core.domain_exceptions import (
    AccessDeniedError,
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.workflows import Workflow
from core.safe_http_errors import raise_internal_server_error
from models.artifacts import ArtifactContentResponse
from models.runs import (
    RUN_LIST_STATUS_FILTERS,
    TERMINAL_RUN_STATUSES,
    WorkflowRunCreate,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowRunSummary,
    WorkflowStepResultResponse,
)
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository
from services.artifacts import ArtifactNotFoundError, FilesystemArtifactService
from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs

logger = logging.getLogger(__name__)


def _step_to_response(step: WorkflowStepResult) -> WorkflowStepResultResponse:
    return WorkflowStepResultResponse(
        id=step.id,
        run_id=step.run_id,
        step_node_id=step.step_node_id,
        step_type=step.step_type,
        step_name=step.step_name,
        status=step.status,
        started_at=step.started_at,
        finished_at=step.finished_at,
        output=step.output,
        error_message=step.error_message,
        error_category=step.error_category,
        error_id=step.error_id,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


def _run_to_summary(run: WorkflowRun, username: str | None) -> WorkflowRunSummary:
    return WorkflowRunSummary(
        id=run.id,
        uuid=run.uuid,
        workflow_id=run.workflow_id,
        triggered_by_id=run.triggered_by_id,
        triggered_by_username=username,
        status=run.status,
        trigger_type=run.trigger_type,
        run_mode=run.run_mode,
        current_node_id=run.current_node_id,
        debug_message=run.debug_message,
        approval_state=run.approval_state,
        device_ids=run.device_ids,
        run_inputs=run.run_inputs,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _run_to_response(
    run: WorkflowRun,
    username: str | None,
    step_results: list[WorkflowStepResult],
) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        uuid=run.uuid,
        workflow_id=run.workflow_id,
        triggered_by_id=run.triggered_by_id,
        triggered_by_username=username,
        status=run.status,
        trigger_type=run.trigger_type,
        run_mode=run.run_mode,
        current_node_id=run.current_node_id,
        debug_message=run.debug_message,
        approval_state=run.approval_state,
        device_ids=run.device_ids,
        run_inputs=run.run_inputs,
        hatchet_run_id=run.hatchet_run_id,
        error_message=run.error_message,
        error_category=run.error_category,
        error_id=run.error_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        step_results=[_step_to_response(s) for s in step_results],
    )


class RunService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.run_repo = RunRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.artifact_service = FilesystemArtifactService(settings.data_directory)

    def _assert_workflow_access(self, workflow_id: int, user_id: int) -> Workflow:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = wf_result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        return workflow

    def trigger_run(
        self,
        workflow_id: int,
        data: WorkflowRunCreate,
        user_id: int,
    ) -> WorkflowRunResponse:
        workflow = self._assert_workflow_access(workflow_id, user_id)

        try:
            run_inputs = resolve_run_inputs(workflow.static_attributes, data.run_inputs)
        except RunInputValidationError as exc:
            raise ValidationFailedError(str(exc)) from exc

        run = self.run_repo.create_run(
            workflow_id=workflow_id,
            triggered_by_id=user_id,
            trigger_type=data.trigger_type,
            device_ids=data.device_ids,
            run_mode=data.run_mode,
            run_inputs=run_inputs,
        )
        logger.info("Created run id=%s workflow_id=%s user_id=%s", run.id, workflow_id, user_id)

        try:
            from hatchet.workflows.dispatch import resolve_dispatch_workflow
            from hatchet.workflows.workflow_run import WorkflowRunInput

            dispatch_workflow = resolve_dispatch_workflow(workflow, self.db)
            ref = dispatch_workflow.run_no_wait(WorkflowRunInput(run_id=run.id))
            hatchet_run_id = str(ref.workflow_run_id or "")
            self.run_repo.update_run_status(run, status="pending", hatchet_run_id=hatchet_run_id)
            logger.info("Dispatched run_id=%s hatchet_run_id=%s", run.id, hatchet_run_id)
        except Exception:
            error_id = str(uuid4())
            logger.error(
                "Failed to dispatch run_id=%s to Hatchet error_id=%s",
                run.id,
                error_id,
                exc_info=True,
                extra={"error_id": error_id},
            )
            self.run_repo.update_run_status(
                run,
                status="failed",
                error_message="Workflow execution engine unavailable",
                error_category="internal",
                error_id=error_id,
            )
            raise_internal_server_error("Workflow execution engine unavailable")

        return _run_to_response(run, None, [])

    def list_runs(
        self,
        workflow_id: int,
        user_id: int,
        *,
        statuses: list[str] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> WorkflowRunListResponse:
        self._assert_workflow_access(workflow_id, user_id)
        if statuses:
            invalid = [s for s in statuses if s not in RUN_LIST_STATUS_FILTERS]
            if invalid:
                raise ValidationFailedError(f"Invalid status filter(s): {', '.join(invalid)}")
        rows = self.run_repo.list_runs_for_workflow(
            workflow_id,
            statuses=statuses,
            created_from=created_from,
            created_to=created_to,
        )
        summaries = [_run_to_summary(run, username) for run, username in rows]
        return WorkflowRunListResponse(runs=summaries, total=len(summaries))

    def get_run(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        step_results = self.run_repo.get_step_results_for_run(run_id)
        return _run_to_response(run, username, step_results)

    def get_run_artifact(
        self, run_id: int, artifact_id: str, user_id: int
    ) -> ArtifactContentResponse:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        try:
            ref, content = self.artifact_service.get_for_run(
                run_uuid=run.uuid, artifact_id=artifact_id
            )
        except ArtifactNotFoundError as exc:
            raise NotFoundError("Artifact not found") from exc

        return ArtifactContentResponse(
            artifact_id=ref.artifact_id,
            kind=ref.kind,
            media_type=ref.media_type,
            size_bytes=ref.size_bytes,
            content=content,
        )

    def cancel_run(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        if run.status not in ("pending", "running", "paused"):
            raise ValidationFailedError(f"Cannot cancel a run with status {run.status!r}")

        if run.hatchet_run_id:
            try:
                from hatchet.client import hatchet

                hatchet.runs.cancel(run.hatchet_run_id)
            except Exception:
                logger.warning("Could not cancel Hatchet run hatchet_run_id=%s", run.hatchet_run_id)

        self.run_repo.update_run_status(run, status="cancelled")
        step_results = self.run_repo.get_step_results_for_run(run_id)
        return _run_to_response(run, username, step_results)

    def delete_run(self, run_id: int, user_id: int) -> None:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        if run.status not in TERMINAL_RUN_STATUSES:
            raise ValidationFailedError(
                f"Cannot delete a run with status {run.status!r}; "
                "only finished runs can be deleted"
            )
        self.run_repo.delete_run(run)
        self.artifact_service.delete_for_run(run.uuid)

    def _assert_not_awaiting_batch_approval(self, run: WorkflowRun) -> None:
        if run.approval_state is not None and run.approval_state.get("awaiting"):
            raise ConflictError("Run is awaiting batch approval, not a debug step")

    def step_run(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        """Advance a paused debug-mode run by exactly one node."""
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        if run.status != "paused" or not run.current_node_id:
            raise ConflictError(f"Run is not paused and awaiting a step (status={run.status!r})")
        self._assert_not_awaiting_batch_approval(run)

        self._push_continue_event(run)
        step_results = self.run_repo.get_step_results_for_run(run_id)
        return _run_to_response(run, username, step_results)

    def continue_run(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        """Resume a paused debug-mode run to completion without further pauses."""
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        if run.status != "paused" or not run.current_node_id:
            raise ConflictError(f"Run is not paused and awaiting a step (status={run.status!r})")
        self._assert_not_awaiting_batch_approval(run)

        run = self.run_repo.update_run_status(run, status="paused", run_mode="normal")
        self._push_continue_event(run)
        step_results = self.run_repo.get_step_results_for_run(run_id)
        return _run_to_response(run, username, step_results)

    def approve_batch(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        """Release the next Wait & Run batch without changing later gates."""
        run, username, state = self._require_awaiting_batch(run_id, user_id)
        self._push_batch_event(run, int(state["next_batch_index"]))
        step_results = self.run_repo.get_step_results_for_run(run_id)
        return _run_to_response(run, username, step_results)

    def approve_all(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        """Release the next Wait & Run batch and skip all further approval gates."""
        run, username, state = self._require_awaiting_batch(run_id, user_id)
        run = self.run_repo.update_run_status(
            run,
            status="paused",
            approval_state={**state, "auto_approve_remaining": True},
        )
        self._push_batch_event(run, int(state["next_batch_index"]))
        step_results = self.run_repo.get_step_results_for_run(run_id)
        return _run_to_response(run, username, step_results)

    def _require_awaiting_batch(
        self, run_id: int, user_id: int
    ) -> tuple[WorkflowRun, str | None, dict]:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)

        state = run.approval_state or {}
        if run.status != "paused" or not state.get("awaiting"):
            raise ConflictError(f"Run is not awaiting batch approval (status={run.status!r})")
        return run, username, state

    def _push_continue_event(self, run: WorkflowRun) -> None:
        from hatchet.client import hatchet
        from services.execution.run_events import debug_step_event_key

        event_key = debug_step_event_key(run.uuid, run.current_node_id or "")
        try:
            # scope must match the scope passed to aio_wait_for_event on the
            # worker side (hatchet/workflows/workflow_run.py) — see the
            # STEP_EVENT_LOOKBACK docstring in services/execution/run_events.py
            # for why this is needed.
            hatchet.event.push(event_key, {}, scope=event_key)
        except Exception:
            logger.error(
                "Failed to push continue event run_id=%s event_key=%s",
                run.id,
                event_key,
                exc_info=True,
            )
            raise_internal_server_error("Workflow execution engine unavailable")

    def _push_batch_event(self, run: WorkflowRun, batch_index: int) -> None:
        from hatchet.client import hatchet
        from services.execution.run_events import batch_approval_event_key

        event_key = batch_approval_event_key(run.uuid, batch_index)
        try:
            # scope must match the scope passed to aio_wait_for_event on the
            # worker side (hatchet/workflows/workflow_run.py) — see the
            # STEP_EVENT_LOOKBACK docstring in services/execution/run_events.py
            # for why this is needed.
            hatchet.event.push(event_key, {}, scope=event_key)
        except Exception:
            logger.error(
                "Failed to push batch approval event run_id=%s event_key=%s",
                run.id,
                event_key,
                exc_info=True,
            )
            raise_internal_server_error("Workflow execution engine unavailable")
