"""Periodic reaper for runs that nothing else can finalise (DN-B, mechanism 4).

A run is written to a terminal state by the orchestration code. When the worker dies or the
24 h task timeout fires, no code is left to do so; this cron asks the engine and finalises
the row. If the engine cannot be reached it does nothing (never reap on silence).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from hatchet_sdk import Context, EmptyModel

from core.config import settings
from hatchet.client import hatchet

logger = logging.getLogger(__name__)

workflow = hatchet.workflow(name="RunReaper", on_crons=[settings.run_reaper_cron_schedule])


@workflow.task(name="reap_stuck_runs")
async def reap_stuck_runs(input: EmptyModel, ctx: Context) -> dict:
    from core.database import SessionLocal
    from services.execution.run_lifecycle_service import RunLifecycleService

    async def engine_status(hatchet_run_id: str) -> str | None:
        try:
            return str((await hatchet.runs.aio_get_status(hatchet_run_id)).value)
        except Exception:  # noqa: BLE001 - engine unreachable or run unknown: leave the row
            logger.debug("Engine status unavailable hatchet_run_id=%s", hatchet_run_id)
            return None

    with SessionLocal() as db:
        reaped = await RunLifecycleService(db).reap_stuck_runs(
            grace=timedelta(minutes=settings.run_reaper_grace_minutes),
            engine_status=engine_status,
        )
    if reaped:
        logger.warning("Run reaper finalised %s stuck run(s)", reaped)
    return {"reaped": reaped}
