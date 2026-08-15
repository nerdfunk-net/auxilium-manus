"""Periodic Hatchet workflow that purges old workflow runs and orphaned
filesystem artifacts.

Runs the same RetentionService as scripts/purge_retention.py, but automatically
inside the app whenever the Hatchet worker is running — no external crontab has
to be installed. Deletes workflow_runs in terminal states older than
RUN_RETENTION_DAYS, then sweeps data/artifacts/ for any artifact whose run_id no
longer matches an existing run.
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
