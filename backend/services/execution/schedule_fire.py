"""Start one run of a schedule's workflow, exactly as a scheduled fire does.

Shared by the Hatchet `ScheduledWorkflowTrigger` task (cron / one-time fire, acting as the
schedule's creator) and `ScheduleService.run_now` (the "Run now" button, acting as the
clicking user). The caller is responsible for authorisation and for `mark_triggered`.

A run that cannot start is persisted as `failed` (never left `pending`) and returned, so the
caller can read `run.status`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from core.config import settings
from core.models.runs import WorkflowRun
from core.models.schedules import WorkflowSchedule
from core.models.workflows import Workflow
from repositories.plugin_repository import PluginRepository
from repositories.run_repository import RunRepository
from services.execution.dispatch_breaker import EngineUnavailableError, dispatch_breaker
from services.execution.reference_resolver import (
    ReferenceValidationError,
    validate_reference_inputs,
)
from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow.workflow_validation_service import WorkflowValidationService

logger = logging.getLogger(__name__)


def start_scheduled_run(
    db: Session,
    schedule: WorkflowSchedule,
    workflow: Workflow,
    *,
    acting_user_id: int | None,
    plugin_registry_service: PluginRegistryService | None = None,
    use_dispatch_breaker: bool = False,
) -> WorkflowRun:
    """Create a `scheduled` run owned by `acting_user_id` and hand it to the engine.

    `acting_user_id` owns the run and scopes credential / inventory resolution.
    `use_dispatch_breaker` is for callers on a web request thread: while the engine is down the
    SDK blocks ~17 s per call (O2-01), so they fail fast and feed the shared breaker. The
    Hatchet worker leaves it off and always tries.
    """
    # Imported here: these pull in the Hatchet workflow objects, which the web process
    # only needs when a run is actually started.
    from hatchet.workflows.dispatch import resolve_dispatch_workflow
    from hatchet.workflows.run_metadata import run_trigger_options
    from hatchet.workflows.workflow_run import WorkflowRunInput

    run_repo = RunRepository(db)
    run = run_repo.create_run(
        workflow_id=schedule.workflow_id,
        triggered_by_id=acting_user_id,
        trigger_type="scheduled",
        device_ids=[],
    )

    # Pre-run gate (doc/ai_collaboration/PROCESS.md): a scheduled run has no operator to
    # prompt, so an unresolved Tier 1-3 validation error hard-fails here exactly like the
    # run-input checks below — same shape, same error_category, no override. Mirrors
    # RunService._assert_no_blocking_validation_errors rather than calling it, because the
    # Hatchet worker has no FastAPI app.state and builds its own PluginRegistryService.
    registry = plugin_registry_service or PluginRegistryService(
        PluginRepository(plugins_file=settings.plugins_file)
    )
    validation = WorkflowValidationService(db, registry).validate(
        workflow.canvas_nodes or [],
        workflow.canvas_edges or [],
        acting_user_id=acting_user_id,
    )
    if validation.has_errors:
        error_summary = "; ".join(
            f"{f.code}: {f.message}" for f in validation.findings if f.severity == "error"
        )
        run_repo.update_run_status(
            run,
            status="failed",
            error_message=f"Blocked by pre-run validation: {error_summary}",
            error_category="configuration",
        )
        logger.info(
            "Scheduled run blocked by pre-run validation run_id=%s workflow_id=%s "
            "schedule_id=%s error=%s",
            run.id,
            schedule.workflow_id,
            schedule.id,
            error_summary,
        )
        return run

    # Values come from the schedule's own run_inputs merged with the workflow's declared
    # defaults. A required attribute still missing, or a `reference` value that no longer
    # resolves for the acting user (inventory deleted, credential rotated), fails this run
    # immediately with a configuration error rather than dispatching an incomplete bag.
    try:
        run_inputs = resolve_run_inputs(workflow.static_attributes, schedule.run_inputs or {})
        validate_reference_inputs(
            workflow.static_attributes,
            run_inputs,
            db=db,
            acting_user_id=acting_user_id,
        )
    except (RunInputValidationError, ReferenceValidationError) as exc:
        run_repo.update_run_status(
            run,
            status="failed",
            error_message=str(exc),
            error_category="configuration",
        )
        logger.info(
            "Scheduled run failed input validation run_id=%s workflow_id=%s "
            "schedule_id=%s error=%s",
            run.id,
            schedule.workflow_id,
            schedule.id,
            exc,
        )
        return run

    run.run_inputs = run_inputs
    db.commit()

    run_id = run.id
    try:
        if use_dispatch_breaker and dispatch_breaker.is_open():
            raise EngineUnavailableError("a recent dispatch to Hatchet failed")
        dispatch_workflow = resolve_dispatch_workflow(workflow, db)
        # Read before the commit below expires the instances.
        trigger_options = run_trigger_options(
            run_id=run_id,
            workflow_name=workflow.name,
            trigger_type="scheduled",
        )
        # End the read transaction first: an open one keeps a pooled connection checked out for
        # the whole Hatchet call, which takes ~17 s to fail when the engine is down (O2-01).
        db.commit()
        ref = dispatch_workflow.run_no_wait(
            WorkflowRunInput(run_id=run_id), options=trigger_options
        )
        if use_dispatch_breaker:
            dispatch_breaker.record_success()
    except Exception:
        if use_dispatch_breaker:
            dispatch_breaker.record_failure()
        # A run that was never handed to the engine must not stay 'pending' (C1-04).
        error_id = str(uuid4())
        logger.error(
            "Scheduled dispatch failed run_id=%s schedule_id=%s error_id=%s",
            run.id,
            schedule.id,
            error_id,
            exc_info=True,
        )
        run_repo.update_run_status(
            run,
            status="failed",
            error_category="internal",
            error_id=error_id,
            error_message="Workflow execution engine unavailable",
            finished_at=datetime.now(UTC),
        )
        return run
    run_repo.record_hatchet_run_id(run, str(ref.workflow_run_id or ""))

    logger.info(
        "Scheduled run dispatched run_id=%s workflow_id=%s schedule_id=%s",
        run.id,
        schedule.workflow_id,
        schedule.id,
    )
    return run
