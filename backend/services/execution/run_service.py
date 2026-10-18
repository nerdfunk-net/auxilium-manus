from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.orm import Session

from core.config import settings
from core.domain_exceptions import (
    AccessDeniedError,
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)
from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.workflows import Workflow
from core.safe_http_errors import raise_internal_server_error
from models.artifacts import ArtifactContentResponse
from models.attribute_path import (
    AttributePathResolveResponse,
    AttributePathResolveResult,
    AttributePathTreeResponse,
)
from models.runs import (
    RUN_LIST_STATUS_FILTERS,
    TERMINAL_RUN_STATUSES,
    DeviceGroupProgress,
    ErrorCategory,
    RunProgress,
    StepProgress,
    WorkflowRunCreate,
    WorkflowRunDeviceGroupResponse,
    WorkflowRunEventListResponse,
    WorkflowRunEventResponse,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowRunSummary,
    WorkflowStepResultResponse,
)
from models.workflow_context import DeviceContext
from repositories.plugin_repository import PluginRepository
from repositories.run_event_repository import RunEventRepository
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository
from services.artifacts import ArtifactNotFoundError, FilesystemArtifactService
from services.execution.dispatch_breaker import (
    ENGINE_UNAVAILABLE_MESSAGE,
    EngineUnavailableError,
    dispatch_breaker,
)
from services.execution.log_attribute_files import delete_run_dir
from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow.workflow_validation_service import WorkflowValidationService
from services.workflow_context.attribute_path import resolve_device_attribute_state
from services.workflow_context.attribute_path_discovery import (
    build_attribute_path_tree,
    merge_ancestor_devices,
)
from services.workflow_context.secret_fields import redact_secrets_in_data

logger = logging.getLogger(__name__)

_ACTIVE_RUN_STATUSES = ("pending", "running", "paused")

# A run started by a step of another run (start-workflow) may itself start runs, to this depth.
MAX_CHILD_RUN_DEPTH = 3
# Worst-first ranking of step statuses, for judging a finished child run.
_STEP_STATUS_SEVERITY = {"failed": 4, "partial": 3, "skipped": 2, "success": 1}


@dataclass(frozen=True)
class ChildRunSnapshot:
    """What a waiting parent step needs to know about a child run: no step output."""

    run_id: int
    status: str
    error_message: str | None
    worst_step_status: str | None
    # node id -> step status, so the parent can tell that a particular step really ran
    step_statuses: dict[str, str] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES


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
        error_category=cast("ErrorCategory | None", step.error_category),
        error_id=step.error_id,
        failure=step.failure,
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
        current_node_id=run.current_node_id,
        debug_message=run.debug_message,
        approval_state=run.approval_state,
        device_ids=run.device_ids,
        run_inputs=redact_secrets_in_data(run.run_inputs),
        parent_run_id=run.parent_run_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _run_to_response(
    run: WorkflowRun,
    username: str | None,
    step_results: list[WorkflowStepResult],
    device_groups: list[WorkflowRunDeviceGroup] | None = None,
) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        uuid=run.uuid,
        workflow_id=run.workflow_id,
        triggered_by_id=run.triggered_by_id,
        triggered_by_username=username,
        status=run.status,
        trigger_type=run.trigger_type,
        current_node_id=run.current_node_id,
        debug_message=run.debug_message,
        approval_state=run.approval_state,
        device_ids=run.device_ids,
        run_inputs=redact_secrets_in_data(run.run_inputs),
        parent_run_id=run.parent_run_id,
        hatchet_run_id=run.hatchet_run_id,
        error_message=run.error_message,
        error_category=cast("ErrorCategory | None", run.error_category),
        error_id=run.error_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        step_results=[_step_to_response(s) for s in step_results],
        device_groups=[
            WorkflowRunDeviceGroupResponse.model_validate(g) for g in (device_groups or [])
        ],
    )


class RunService:
    def __init__(
        self, db: Session, plugin_registry_service: PluginRegistryService | None = None
    ) -> None:
        self.db = db
        self.run_repo = RunRepository(db)
        self.event_repo = RunEventRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.artifact_service = FilesystemArtifactService(settings.data_directory)
        self._plugin_registry_service = plugin_registry_service

    def _validator(self) -> WorkflowValidationService:
        # Callers that already have the app-wide cached PluginRegistryService
        # (routers, via Depends(get_plugin_service)) should pass it in; anyone
        # else (ChangeRequestService, which never threads one through) gets a
        # freshly-built one here — same one-file-parse-per-call construction
        # ai_workflow_apply.py/ai_defaults.py already use, cheap enough for an
        # infrequent gate check.
        registry_service = self._plugin_registry_service or PluginRegistryService(
            PluginRepository(plugins_file=settings.plugins_file)
        )
        return WorkflowValidationService(self.db, registry_service)

    def _assert_no_blocking_validation_errors(
        self, workflow: Workflow, *, acting_user_id: int | None
    ) -> None:
        """Refuse to run a workflow with unresolved Tier 1-3 validation errors
        — see doc/ai_collaboration/VALIDATION_PLAN.md's "pre-run gate" and
        PROCESS.md's "Pre-run validation gate" open item. Unconditional: no
        override, matching the existing convention for a scheduled trigger's
        run-input validation (hatchet/workflows/scheduled_trigger.py), which
        already hard-fails the same way with no bypass. Tier 4 findings are
        advisory-only (severity="warning") and never block, per
        WorkflowValidationResult.has_errors' own definition."""
        validation = self._validator().validate(
            workflow.canvas_nodes or [],
            workflow.canvas_edges or [],
            acting_user_id=acting_user_id,
        )
        if not validation.has_errors:
            return
        error_summary = "; ".join(
            f"{f.code}: {f.message}" for f in validation.findings if f.severity == "error"
        )
        raise ValidationFailedError(
            f"Cannot run: workflow has unresolved validation errors — {error_summary}"
        )

    def _assert_workflow_access(self, workflow_id: int, user_id: int) -> Workflow:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = wf_result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        return workflow

    def _run_owner_id(self, run: WorkflowRun) -> int | None:
        """Who owns a run: whoever triggered it; a run without a triggering user (webhook
        deploy, schedule without a user) belongs to the workflow's creator."""
        if run.triggered_by_id is not None:
            return run.triggered_by_id
        wf_result = self.wf_repo.get_by_id(run.workflow_id)
        return wf_result[0].creator_id if wf_result else None

    def _assert_run_control(self, run: WorkflowRun, user_id: int, *, allow_admin: bool) -> None:
        """Only the person who started the run may cancel, approve or delete it (S2-03).

        An administrator may cancel or delete (never approve a batch) as an audited exception
        for stuck runs."""
        owner_id = self._run_owner_id(run)
        if owner_id is not None and owner_id == user_id:
            return
        from services.auth.rbac_service import RBACService

        if allow_admin and RBACService(self.db).has_role(user_id, "admin"):
            logger.warning(
                "run_control_admin_override user_id=%s run_id=%s owner_id=%s",
                user_id,
                run.id,
                owner_id,
            )
            return
        raise AccessDeniedError("Only the user who started this run can do that")

    def _create_and_dispatch_run(
        self,
        workflow: Workflow,
        *,
        triggered_by_id: int | None,
        trigger_type: str,
        device_ids: list[str],
        run_inputs: dict[str, Any],
        change_request_id: int | None = None,
        parent_run_id: int | None = None,
        ancestor_workflow_ids: list[int] | None = None,
    ) -> WorkflowRun:
        """Create a WorkflowRun and dispatch it into the Hatchet engine.

        The blessed run-creation path for interactive triggers — shared by
        manual triggers (``trigger_run``) and change-request approvals
        (``ChangeRequestService._dispatch_deploy``). NOT shared by scheduled
        triggers despite what an earlier version of this docstring claimed —
        ``hatchet/workflows/scheduled_trigger.py`` has its own independent
        run-creation code (no interactive caller to raise an exception at, so
        it creates the run row unconditionally and marks it ``failed`` on any
        precondition failure instead); that file's own pre-run validation
        check mirrors the one below. ``run_inputs`` must already be
        resolved/validated by the caller (the approval path replays captured
        inputs verbatim and must NOT re-resolve ``reference`` values the
        approver cannot see). Refuses (``ValidationFailedError``, before any
        run row is created) if the workflow has unresolved Tier 1-3 validation
        errors — see ``_assert_no_blocking_validation_errors``. On a dispatch
        failure the run is marked ``failed`` and a 500 is raised.
        """
        self._assert_no_blocking_validation_errors(workflow, acting_user_id=triggered_by_id)
        run = self.run_repo.create_run(
            workflow_id=workflow.id,
            triggered_by_id=triggered_by_id,
            trigger_type=trigger_type,
            device_ids=device_ids,
            run_inputs=run_inputs,
            parent_run_id=parent_run_id,
            ancestor_workflow_ids=ancestor_workflow_ids,
        )
        if change_request_id is not None:
            run.change_request_id = change_request_id
            self.db.commit()
        logger.info(
            "Created run id=%s workflow_id=%s triggered_by=%s trigger_type=%s",
            run.id,
            workflow.id,
            triggered_by_id,
            trigger_type,
        )

        run_id = run.id
        try:
            if dispatch_breaker.is_open():
                raise EngineUnavailableError("a recent dispatch to Hatchet failed")
            from hatchet.workflows.dispatch import resolve_dispatch_workflow
            from hatchet.workflows.run_metadata import run_trigger_options
            from hatchet.workflows.workflow_run import WorkflowRunInput

            dispatch_workflow = resolve_dispatch_workflow(workflow, self.db)
            # Read before the commit below expires the instance.
            trigger_options = run_trigger_options(
                run_id=run_id,
                workflow_name=workflow.name,
                trigger_type=trigger_type,
                parent_run_id=parent_run_id,
            )
            # End the read transaction first: an open one keeps a pooled connection checked out for
            # the whole Hatchet call, which takes ~17 s to fail when the engine is down (O2-01).
            self.db.commit()
            ref = dispatch_workflow.run_no_wait(
                WorkflowRunInput(run_id=run_id), options=trigger_options
            )
            dispatch_breaker.record_success()
            hatchet_run_id = str(ref.workflow_run_id or "")
            self.run_repo.update_run_status(run, status="pending", hatchet_run_id=hatchet_run_id)
            logger.info("Dispatched run_id=%s hatchet_run_id=%s", run_id, hatchet_run_id)
        except Exception as exc:
            if not isinstance(exc, EngineUnavailableError):
                dispatch_breaker.record_failure()
            error_id = str(uuid4())
            logger.error(
                "Failed to dispatch run_id=%s to Hatchet error_id=%s",
                run_id,
                error_id,
                exc_info=not isinstance(exc, EngineUnavailableError),
                extra={"error_id": error_id},
            )
            self.run_repo.update_run_status(
                run,
                status="failed",
                error_message="Workflow execution engine unavailable",
                error_category="internal",
                error_id=error_id,
            )
            raise_internal_server_error(
                logger,
                "Workflow execution engine unavailable",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                public_message=ENGINE_UNAVAILABLE_MESSAGE,
            )

        return run

    def require_child_target(self, parent_run: WorkflowRun, workflow_id: int) -> Workflow:
        """The workflow ``parent_run`` may start: its triggering user must see it and hold
        ``workflows:execute``. Raises the domain error that says why not."""
        user_id = parent_run.triggered_by_id
        if user_id is None:
            raise ValidationFailedError(
                "A workflow can only be started from a run that has a triggering user"
            )
        workflow = self._assert_workflow_access(workflow_id, user_id)

        from services.auth.rbac_service import RBACService

        if not RBACService(self.db).has_permission(user_id, "workflows", "execute"):
            raise AccessDeniedError("You are not allowed to run workflows")
        return workflow

    def start_child_run(
        self,
        parent_run: WorkflowRun,
        workflow_id: int,
        *,
        run_inputs: dict[str, Any],
    ) -> WorkflowRun:
        """Start ``workflow_id`` as a run of its own on behalf of ``parent_run`` (start-workflow).

        The child runs as the parent's triggering user, who needs access to the workflow and
        ``workflows:execute`` -- the same bar a manual trigger or a schedule fire has. A workflow
        can never (transitively) start itself and the chain is limited to MAX_CHILD_RUN_DEPTH.
        Devices reach the child only as a declared run input (a Get from User ``device_param``),
        like a schedule or a manual run supplies them; nothing else is handed over.
        """
        self._assert_parent_active(parent_run)
        workflow = self.require_child_target(parent_run, workflow_id)
        user_id = cast("int", parent_run.triggered_by_id)
        ancestors = self._child_run_ancestors(parent_run, workflow.id)
        try:
            resolved_inputs = resolve_run_inputs(workflow.static_attributes, run_inputs)
        except RunInputValidationError as exc:
            raise ValidationFailedError(str(exc)) from exc

        child = self._create_and_dispatch_run(
            workflow,
            triggered_by_id=user_id,
            trigger_type="workflow",
            device_ids=[],
            run_inputs=resolved_inputs,
            parent_run_id=parent_run.id,
            ancestor_workflow_ids=ancestors,
        )
        # Cancelling the parent marks it and then sweeps its children once, so a child created
        # after that sweep would be missed. Look again now that the child exists: either the sweep
        # sees it, or this does.
        if not self._parent_is_active(parent_run):
            self._cancel_active_run(child)
            raise ValidationFailedError(
                f"The calling run ended ({parent_run.status}) while the workflow was being started"
            )
        return child

    def _parent_is_active(self, parent_run: WorkflowRun) -> bool:
        self.db.refresh(parent_run)
        return parent_run.status in _ACTIVE_RUN_STATUSES

    def _assert_parent_active(self, parent_run: WorkflowRun) -> None:
        if not self._parent_is_active(parent_run):
            raise ValidationFailedError(
                f"The calling run is no longer active ({parent_run.status}); "
                "it cannot start another workflow"
            )

    def _child_run_ancestors(self, parent_run: WorkflowRun, workflow_id: int) -> list[int]:
        """Workflow ids above a new child, root first, after checking the chain is allowed.

        Read from the list stored on the parent, not by walking ``parent_run_id``: that link is
        cleared when a finished ancestor is deleted or purged, which would let a descendant that
        is still running start its ancestors again with no depth limit.
        """
        chain = [*(parent_run.ancestor_workflow_ids or []), parent_run.workflow_id]
        if workflow_id in chain:
            raise ValidationFailedError(
                "A workflow cannot start itself, directly or through the workflows that started it"
            )
        if len(chain) > MAX_CHILD_RUN_DEPTH:
            raise ValidationFailedError(
                f"Workflows can start other workflows at most {MAX_CHILD_RUN_DEPTH} levels deep"
            )
        return chain

    def child_run_snapshot(self, run_id: int) -> ChildRunSnapshot:
        """The state of a child run a waiting step polls; reads fresh data on every call."""
        run = self.run_repo.get_run(run_id)
        if run is None:
            raise NotFoundError("Run not found")
        self.db.refresh(run)
        rows = self.run_repo.get_step_results_for_run(run_id)
        statuses = [row.status for row in rows]
        worst = max(statuses, key=lambda s: _STEP_STATUS_SEVERITY.get(s, 0), default=None)
        return ChildRunSnapshot(
            run_id=run.id,
            status=run.status,
            error_message=run.error_message,
            worst_step_status=worst,
            step_statuses={row.step_node_id: row.status for row in rows},
        )

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

        run = self._create_and_dispatch_run(
            workflow,
            triggered_by_id=user_id,
            trigger_type=data.trigger_type,
            device_ids=data.device_ids,
            run_inputs=run_inputs,
        )
        return _run_to_response(run, None, [])

    def list_runs(
        self,
        workflow_id: int,
        user_id: int,
        *,
        statuses: list[str] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> WorkflowRunListResponse:
        self._assert_workflow_access(workflow_id, user_id)
        if statuses:
            invalid = [s for s in statuses if s not in RUN_LIST_STATUS_FILTERS]
            if invalid:
                raise ValidationFailedError(f"Invalid status filter(s): {', '.join(invalid)}")
        rows, total = self.run_repo.list_runs_for_workflow(
            workflow_id,
            statuses=statuses,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
        summaries = [_run_to_summary(run, username) for run, username in rows]
        return WorkflowRunListResponse(runs=summaries, total=total, limit=limit, offset=offset)

    def _response(self, run: WorkflowRun, username: str | None) -> WorkflowRunResponse:
        """Full run detail: step results plus live fan-out device-group progress."""
        return _run_to_response(
            run,
            username,
            self.run_repo.get_step_results_for_run(run.id),
            self.run_repo.list_device_groups(run.id),
        )

    def get_run(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        return self._response(run, username)

    def get_run_progress(self, run_id: int, user_id: int) -> RunProgress:
        """The light state of a run for polling: statuses and timestamps, never step output."""
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        return RunProgress(
            id=run.id,
            status=run.status,
            current_node_id=run.current_node_id,
            approval_state=run.approval_state,
            error_message=run.error_message,
            started_at=run.started_at,
            finished_at=run.finished_at,
            steps=[
                StepProgress(
                    step_node_id=row.step_node_id,
                    status=row.status,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    has_error=bool(row.error_message),
                )
                for row in self.run_repo.get_step_progress_rows(run.id)
            ],
            device_groups=[
                DeviceGroupProgress(
                    child_index=group.child_index,
                    status=group.status,
                    node_states=dict(group.node_states or {}),
                    started_at=group.started_at,
                    finished_at=group.finished_at,
                )
                for group in self.run_repo.list_device_groups(run.id)
            ],
        )

    def list_events(
        self, run_id: int, user_id: int, after_id: int = 0, limit: int = 500
    ) -> WorkflowRunEventListResponse:
        """Live run events newer than ``after_id`` (poll with the returned cursor)."""
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        events = self.event_repo.list_events(run_id, after_id=after_id, limit=limit)
        return WorkflowRunEventListResponse(
            events=[WorkflowRunEventResponse.model_validate(e) for e in events],
            next_after_id=events[-1].id if events else after_id,
        )

    def list_latest_events(
        self, run_id: int, user_id: int, limit: int, node_id: str | None = None
    ) -> WorkflowRunEventListResponse:
        """The newest ``limit`` events, oldest first. Same visibility rules as ``list_events``."""
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        events = self.event_repo.list_latest_events(run_id, limit=limit, node_id=node_id)
        return WorkflowRunEventListResponse(
            events=[WorkflowRunEventResponse.model_validate(e) for e in events],
            next_after_id=events[-1].id if events else 0,
        )

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

    def _merged_ancestor_devices(
        self, run_id: int, user_id: int, ancestor_node_ids: list[str]
    ) -> tuple[int, dict[str, DeviceContext], list[str]]:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        step_results = self.run_repo.get_step_results_for_run(run_id)
        devices, matched_node_ids = merge_ancestor_devices(step_results, set(ancestor_node_ids))
        return run.id, devices, matched_node_ids

    def get_attribute_path_tree(
        self, run_id: int, user_id: int, ancestor_node_ids: list[str]
    ) -> AttributePathTreeResponse:
        """Enumerate attribute paths discoverable from this run's ancestor steps.

        ``ancestor_node_ids`` is computed client-side from the current canvas
        graph and trusted as-is — it's a UX correctness filter (don't suggest
        paths a downstream step hasn't produced), not a confidentiality
        boundary: a caller with access to this run can already see every
        step's output via ``get_run``.
        """
        resolved_run_id, devices, matched_node_ids = self._merged_ancestor_devices(
            run_id, user_id, ancestor_node_ids
        )
        return AttributePathTreeResponse(
            run_id=resolved_run_id,
            ancestor_node_ids=matched_node_ids,
            device_count=len(devices),
            nodes=build_attribute_path_tree(devices),
        )

    def resolve_attribute_path(
        self, run_id: int, user_id: int, path: str, ancestor_node_ids: list[str]
    ) -> AttributePathResolveResponse:
        """Resolve one path against this run's merged ancestor devices.

        Reuses ``resolve_device_attribute_state`` verbatim — the same
        function ``route-on-attribute`` calls at execution time — so path
        semantics are never reimplemented for this preview.
        """
        resolved_run_id, devices, _matched_node_ids = self._merged_ancestor_devices(
            run_id, user_id, ancestor_node_ids
        )
        results = []
        for device in devices.values():
            state, value = resolve_device_attribute_state(device, path)
            results.append(
                AttributePathResolveResult(
                    device_id=device.id,
                    device_name=device.name,
                    state=state.value,
                    value=value,
                )
            )
        return AttributePathResolveResponse(run_id=resolved_run_id, results=results)

    def _cancel_active_run(self, run: WorkflowRun) -> bool:
        """Cancel one active run in the database and, best effort, in the engine.

        False when the run had already finished (the caller decides if that is an error).
        """
        # The database says "cancelled" first and is sticky; the engine cancel is best effort,
        # the walk stops at the next step boundary either way (C1-03).
        won = self.run_repo.transition_run(
            run.id, to_status="cancelled", fields={"finished_at": datetime.now(UTC)}
        )
        self.db.refresh(run)
        if not won:
            return False
        self.run_repo.finalise_open_step_results(run.id, message="Cancelled by the operator")
        if run.hatchet_run_id:
            try:
                from hatchet.client import hatchet

                hatchet.runs.cancel(run.hatchet_run_id)
            except Exception:
                logger.warning(
                    "Could not cancel Hatchet run hatchet_run_id=%s",
                    run.hatchet_run_id,
                    exc_info=True,
                )
                # the row is already terminal, so update_run_status would be refused; the note
                # is written with an explicit cancelled -> cancelled transition
                self.run_repo.transition_run(
                    run.id,
                    to_status="cancelled",
                    from_statuses=("cancelled",),
                    fields={
                        "debug_message": (
                            "The engine could not be reached; the run is cancelled here and the "
                            "worker stops at the next step boundary."
                        )
                    },
                )
                self.db.refresh(run)
        return True

    def cancel_child_runs(self, parent_run_id: int, _seen: set[int] | None = None) -> None:
        """Cancel the still-active runs a run's start-workflow steps caused, at any depth.

        Used when the parent is cancelled by an operator and when it is finalised as interrupted:
        nobody is left to judge or gate on those runs. The walk goes through finished children
        too, because a child started without waiting, or one that hit its wait timeout, can be
        done while its own children still run.
        """
        seen = {parent_run_id} if _seen is None else _seen
        for child in self.run_repo.list_children(parent_run_id):
            if child.id in seen:
                continue
            seen.add(child.id)
            if child.status in _ACTIVE_RUN_STATUSES and self._cancel_active_run(child):
                logger.info("Cancelled child run_id=%s of ended run_id=%s", child.id, parent_run_id)
            self.cancel_child_runs(child.id, seen)

    def cancel_run(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        self._assert_run_control(run, user_id, allow_admin=True)

        if run.status not in ("pending", "running", "paused"):
            raise ValidationFailedError(f"Cannot cancel a run with status {run.status!r}")

        if not self._cancel_active_run(run):
            raise ConflictError(f"Run already finished with status {run.status!r}")
        self.cancel_child_runs(run.id)
        from services.change_requests.change_request_service import maybe_reconcile_deploy_run

        maybe_reconcile_deploy_run(self.db, run)
        return self._response(run, username)

    def delete_run(self, run_id: int, user_id: int) -> None:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, _username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        self._assert_run_control(run, user_id, allow_admin=True)

        if run.status not in TERMINAL_RUN_STATUSES:
            raise ValidationFailedError(
                f"Cannot delete a run with status {run.status!r}; only finished runs can be deleted"
            )
        self.run_repo.delete_run(run)
        self.artifact_service.delete_for_run(run.uuid)
        delete_run_dir(run.workflow_id, run.uuid)

    def approve_batch(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        """Release the next Wait & Run batch without changing later gates."""
        run, username, state = self._require_awaiting_batch(run_id, user_id)
        self._push_batch_event(run, int(state["next_batch_index"]))
        return self._response(run, username)

    def approve_all(self, run_id: int, user_id: int) -> WorkflowRunResponse:
        """Release the next Wait & Run batch and skip all further approval gates."""
        run, username, state = self._require_awaiting_batch(run_id, user_id)
        run = self.run_repo.update_run_status(
            run,
            status="paused",
            approval_state={**state, "auto_approve_remaining": True},
        )
        self._push_batch_event(run, int(state["next_batch_index"]))
        return self._response(run, username)

    def _require_awaiting_batch(
        self, run_id: int, user_id: int
    ) -> tuple[WorkflowRun, str | None, dict]:
        result = self.run_repo.get_run_by_id(run_id)
        if result is None:
            raise NotFoundError("Run not found")
        run, username = result
        self._assert_workflow_access(run.workflow_id, user_id)
        self._assert_run_control(run, user_id, allow_admin=False)

        state = run.approval_state or {}
        if run.status != "paused" or not state.get("awaiting"):
            raise ConflictError(f"Run is not awaiting batch approval (status={run.status!r})")
        return run, username, state

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
            raise_internal_server_error(
                logger,
                "Workflow execution engine unavailable",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                public_message=ENGINE_UNAVAILABLE_MESSAGE,
            )
