"""Periodic Hatchet workflow for background housekeeping.

Two independent tasks run on the same cron:

* ``purge_retention`` — deletes workflow_runs in terminal states older than
  RUN_RETENTION_DAYS (gated on RUN_RETENTION_ENABLED), then sweeps
  data/artifacts/ for any artifact whose run_id no longer matches a run. Same
  RetentionService as scripts/purge_retention.py.
* ``reconcile_change_requests`` — expires stale ``staged`` change requests past
  their TTL and finalises any ``deploying`` change request whose deploy run
  already reached a terminal status but whose detail page nobody opened (the
  detail GET reconciles on read; this catches the rest). See
  ``doc/CICD_PIPELINE.md``.

Runs automatically inside the app whenever the Hatchet worker is up — no
external crontab required.
"""

from __future__ import annotations

import logging

from hatchet_sdk import Context, EmptyModel

from core.config import settings
from hatchet.client import hatchet

logger = logging.getLogger(__name__)

workflow = hatchet.workflow(
    name="PurgeWorkflowRunRetention",
    on_crons=[settings.run_retention_cron_schedule],
)


@workflow.task(name="purge_retention")
async def purge_retention(input: EmptyModel, ctx: Context) -> dict:
    from core.database import SessionLocal
    from services.execution.retention_service import RetentionService

    if not settings.run_retention_enabled:
        logger.info("Run retention disabled (RUN_RETENTION_ENABLED=false); skipping purge")
        return {"skipped": True}

    with SessionLocal() as db:
        result = RetentionService(db).purge_workflow_runs(
            retention_days=settings.run_retention_days,
            batch_size=settings.run_retention_batch_size,
        )

    logger.info(
        "Purged %s run(s) and %s orphaned artifact(s) older than %s day(s)",
        result.runs_deleted,
        result.artifacts_deleted,
        result.retention_days,
    )
    return {
        "runs_deleted": result.runs_deleted,
        "artifacts_deleted": result.artifacts_deleted,
        "retention_days": result.retention_days,
    }


@workflow.task(name="reconcile_change_requests")
async def reconcile_change_requests(input: EmptyModel, ctx: Context) -> dict:
    from core.database import SessionLocal
    from services.change_requests.change_request_service import ChangeRequestService

    with SessionLocal() as db:
        service = ChangeRequestService(db)
        expired = service.expire_sweep()
        finalised = service.reconcile_all_in_flight()

    if expired or finalised:
        logger.info(
            "Change-request sweep: %s expired, %s finalised", expired, finalised
        )
    return {"expired": expired, "finalised": finalised}
