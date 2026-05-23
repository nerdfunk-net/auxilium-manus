from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.retention import WorkflowRunRetentionResult
from repositories.run_repository import RunRepository

logger = logging.getLogger(__name__)


class RetentionService:
    def __init__(self, db: Session) -> None:
        self.run_repo = RunRepository(db)

    def purge_workflow_runs(
        self,
        *,
        retention_days: int,
        batch_size: int,
        dry_run: bool = False,
    ) -> WorkflowRunRetentionResult:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        logger.info(
            "Workflow run retention cutoff=%s retention_days=%s dry_run=%s",
            cutoff.isoformat(),
            retention_days,
            dry_run,
        )

        if dry_run:
            count = self.run_repo.count_finished_runs_older_than(cutoff=cutoff)
            logger.info("Would delete %s finished workflow run(s)", count)
            return WorkflowRunRetentionResult(
                dry_run=True,
                retention_days=retention_days,
                cutoff=cutoff,
                runs_deleted=count,
            )

        deleted = self.run_repo.purge_finished_runs_older_than(
            cutoff=cutoff,
            batch_size=batch_size,
        )
        logger.info("Deleted %s finished workflow run(s)", deleted)
        return WorkflowRunRetentionResult(
            dry_run=False,
            retention_days=retention_days,
            cutoff=cutoff,
            runs_deleted=deleted,
        )
