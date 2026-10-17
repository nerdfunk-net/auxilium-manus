"""Run lifecycle safety net: finalise runs the orchestration could not finish (DN-B)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from repositories.run_repository import RunRepository
from services.change_requests.change_request_service import maybe_reconcile_deploy_run

logger = logging.getLogger(__name__)

EngineStatus = Callable[[str], Awaitable[str | None]]


class RunLifecycleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RunRepository(db)

    def fail_interrupted(
        self,
        run_id: int,
        *,
        message: str,
        category: str = "internal",
        error_id: str | None = None,
    ) -> bool:
        """Finalise a run the orchestration could not finish. False when it was already
        terminal (cancelled by the operator, or finished) - then nothing is changed."""
        error_id = error_id or str(uuid4())
        changed = self.repo.transition_run(
            run_id,
            to_status="failed",
            fields={
                "error_message": message,
                "error_category": category,
                "error_id": error_id,
                "finished_at": datetime.now(UTC),
            },
        )
        if not changed:
            return False
        self.repo.finalise_open_step_results(run_id, message=message)
        logger.error("Run interrupted run_id=%s error_id=%s", run_id, error_id)
        found = self.repo.get_run_by_id(run_id)
        if found is not None:
            maybe_reconcile_deploy_run(self.db, found[0])
        return True

    async def reap_stuck_runs(self, *, grace: timedelta, engine_status: EngineStatus) -> int:
        """Finalise active runs older than ``grace`` that the engine no longer runs.

        Never reaps on silence: an unreachable engine (``None``) leaves the run alone.
        """
        cutoff = datetime.now(UTC) - grace
        reaped = 0
        for run in self.repo.list_active_runs_older_than(cutoff):
            run_id = run.id
            if not run.hatchet_run_id:
                if run.status == "pending" and self.fail_interrupted(
                    run_id, message="The run was never handed to the engine."
                ):
                    reaped += 1
                continue
            status = await engine_status(run.hatchet_run_id)
            if status is None:
                continue
            upper = status.upper()
            if "COMPLETED" in upper:
                message = "The engine finished the task but no result was recorded."
            elif "FAILED" in upper or "CANCELLED" in upper:
                message = "The engine ended the task before the run finished."
            else:
                continue
            if self.fail_interrupted(run_id, message=message):
                reaped += 1
        return reaped
