"""Operator view of what the Hatchet engine reports for a run and for the workers.

Read-only and best-effort: the engine being down is the case this view exists for, so an SDK
failure becomes ``engine_reachable=False`` with a fixed message (never the exception text).
Task input/output are never requested or returned: they can hold device data and secrets.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any

from hatchet_sdk.clients.rest.exceptions import NotFoundException
from hatchet_sdk.clients.rest.models.v1_task_status import V1TaskStatus
from hatchet_sdk.clients.rest.models.worker_status import WorkerStatus

from hatchet.client import hatchet
from hatchet.dynamic_worker_config import DYNAMIC_WORKER_NAME
from hatchet.worker_config import WORKER_NAME
from models.hatchet import (
    HatchetChildRun,
    HatchetChildSummary,
    HatchetRunDiagnostics,
    HatchetTaskEventInfo,
    HatchetTaskInfo,
    HatchetWorkerInfo,
    HatchetWorkersResponse,
)
from models.runs import WorkflowRunResponse
from services.git.scrub import scrub_url_credentials
from services.hatchet.hatchet_settings_service import dashboard_run_url

logger = logging.getLogger(__name__)

EXPECTED_WORKERS: tuple[str, ...] = (WORKER_NAME, DYNAMIC_WORKER_NAME)

_ACTIVE_RUN_STATUSES = frozenset({"pending", "running", "paused"})
_ENGINE_TERMINAL = frozenset(
    {V1TaskStatus.COMPLETED.value, V1TaskStatus.FAILED.value, V1TaskStatus.CANCELLED.value}
)
_PROBLEM_STATUSES = [V1TaskStatus.FAILED, V1TaskStatus.CANCELLED]
_ACTIVE_STATUSES = [V1TaskStatus.RUNNING, V1TaskStatus.QUEUED]
_ENGINE_LIVE = frozenset({V1TaskStatus.QUEUED.value, V1TaskStatus.RUNNING.value})

_MAX_TEXT = 2000
_MAX_EVENTS = 200
# Completed groups are only counted; the rows are the ones that need attention.
_MAX_PROBLEM_ROWS = 100
_MAX_ACTIVE_ROWS = 50
# The SDK warns about plain list windows of 7 days or more and offers a per-day paginated list.
_PLAIN_LIST_WINDOW = timedelta(days=7)
# Bounds the per-day requests for a very long run; beyond it the summary is marked truncated.
_MAX_SPAN = timedelta(days=30)
# Children are created before the run finishes; this slack covers clock skew.
_FINISH_SLACK = timedelta(minutes=5)
# The SDK's REST client sets no timeout, and this view exists for an unresponsive engine.
_ENGINE_TIMEOUT_SECONDS = 10.0

_UNREACHABLE = "The Hatchet engine could not be reached. See the backend log for details."


async def _bounded[T](awaitable: Awaitable[T]) -> T:
    return await asyncio.wait_for(awaitable, timeout=_ENGINE_TIMEOUT_SECONDS)


def _child_window(run: WorkflowRunResponse) -> tuple[datetime, datetime, bool]:
    """The run's whole span (creation to finish, or now), bounded; True when it was cut short."""
    since = run.created_at if run.created_at.tzinfo else run.created_at.replace(tzinfo=UTC)
    finished = run.finished_at
    if finished is not None and finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    now = datetime.now(tz=UTC)
    until = min(now, finished + _FINISH_SLACK) if finished is not None else now
    if until - since > _MAX_SPAN:
        return since, since + _MAX_SPAN, True
    return since, until, False


def _text(value: str | None) -> str | None:
    """Engine free text: credentials in URLs masked, length capped."""
    if not value:
        return None
    cleaned = scrub_url_credentials(value)
    return cleaned if len(cleaned) <= _MAX_TEXT else cleaned[:_MAX_TEXT] + "…"


def _is_worker(expected: str, name: str) -> bool:
    """Exact worker name, ignoring the Hatchet namespace prefix (a substring would match a
    debug copy such as ``<name>-debug`` and hide a dead worker)."""
    namespace = hatchet.config.namespace or ""
    return name == expected or (bool(namespace) and name.removeprefix(namespace) == expected)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def status_mismatch(run_status: str, engine_status: str | None) -> str | None:
    """Describe a clear contradiction between our run status and the engine's, else None."""
    if engine_status is None:
        if run_status in _ACTIVE_RUN_STATUSES:
            return "The run is active here but the engine has no record of it."
        return None
    if run_status in _ACTIVE_RUN_STATUSES and engine_status in _ENGINE_TERMINAL:
        return (
            f"The engine reports {engine_status} but the run is still {run_status} here "
            "(a lost status update; the run reaper finalises it)."
        )
    if run_status not in _ACTIVE_RUN_STATUSES and engine_status in _ENGINE_LIVE:
        return f"The run is {run_status} here but the engine still reports {engine_status}."
    return None


def _task_info(task: Any) -> HatchetTaskInfo:
    return HatchetTaskInfo(
        name=task.display_name,
        status=_enum_value(task.status),
        attempt=task.attempt,
        retry_count=task.retry_count,
        started_at=task.started_at,
        finished_at=task.finished_at,
        duration_ms=task.duration,
        error_message=_text(task.error_message),
    )


def _event_info(event: Any) -> HatchetTaskEventInfo:
    return HatchetTaskEventInfo(
        task_name=event.task_display_name,
        event_type=_enum_value(event.event_type),
        timestamp=event.timestamp,
        message=_text(event.message) or "",
        error_message=_text(event.error_message),
        attempt=event.attempt,
    )


_COUNT_KEYS = ("completed", "failed", "cancelled", "running", "queued")


_STATUS_RANK = {"FAILED": 0, "CANCELLED": 1, "RUNNING": 2, "QUEUED": 3}


def _child_sort_key(child: HatchetChildRun) -> tuple[int, int]:
    """Failed, cancelled, running, queued; then by group number (non-numeric last)."""
    index = int(child.child_index) if (child.child_index or "").isdigit() else 10**9
    return (_STATUS_RANK.get(child.status, len(_STATUS_RANK)), index)


def _child_info(task: Any) -> HatchetChildRun:
    metadata = task.additional_metadata or {}
    child_index = metadata.get("child_index")
    return HatchetChildRun(
        hatchet_run_id=task.workflow_run_external_id,
        name=task.display_name,
        status=_enum_value(task.status),
        child_index=None if child_index is None else str(child_index),
        started_at=task.started_at,
        finished_at=task.finished_at,
        error_message=_text(task.error_message),
    )


class HatchetDiagnosticsService:
    async def get_run_diagnostics(self, run: WorkflowRunResponse) -> HatchetRunDiagnostics:
        hatchet_run_id = run.hatchet_run_id
        link = dashboard_run_url(hatchet_run_id)
        if not hatchet_run_id:
            return HatchetRunDiagnostics(
                engine_reachable=True,
                message="This run was never handed to the engine.",
                mismatch=status_mismatch(run.status, None),
            )
        try:
            details = await _bounded(hatchet.runs.aio_get(hatchet_run_id))
        except NotFoundException:
            return HatchetRunDiagnostics(
                engine_reachable=True,
                message="The engine has no record of this run (never dispatched, or purged).",
                hatchet_run_id=hatchet_run_id,
                mismatch=status_mismatch(run.status, None),
                dashboard_url=link,
            )
        except Exception:
            logger.warning("Hatchet run lookup failed run_id=%s", run.id, exc_info=True)
            return HatchetRunDiagnostics(
                engine_reachable=False,
                message=_UNREACHABLE,
                hatchet_run_id=hatchet_run_id,
                dashboard_url=link,
            )

        engine_status = _enum_value(details.run.status)
        child_summary, child_runs = await self._children(run, details)
        return HatchetRunDiagnostics(
            engine_reachable=True,
            message="OK",
            hatchet_run_id=hatchet_run_id,
            engine_status=engine_status,
            mismatch=status_mismatch(run.status, engine_status),
            dashboard_url=link,
            tasks=[_task_info(t) for t in details.tasks],
            events=[_event_info(e) for e in details.task_events[-_MAX_EVENTS:]],
            child_runs=child_runs,
            child_summary=child_summary,
            events_truncated=len(details.task_events) > _MAX_EVENTS,
        )

    async def _children(
        self, run: WorkflowRunResponse, details: Any
    ) -> tuple[HatchetChildSummary | None, list[HatchetChildRun]]:
        """Fan-out groups and child workflows: exact counts, plus the rows that need attention.

        Rows come from the ``parent_run_id`` metadata; the counts from the engine's task metrics
        for the parent run's spawning task(s), which have no row limit.
        """
        since, until, capped = _child_window(run)
        spawning = [t for t in details.tasks if (t.num_spawned_children or 0) > 0]
        counts, problems, active = await asyncio.gather(
            self._child_counts(spawning, since, until),
            self._list_children(run, since, until, _PROBLEM_STATUSES, _MAX_PROBLEM_ROWS),
            self._list_children(run, since, until, _ACTIVE_STATUSES, _MAX_ACTIVE_ROWS),
        )
        rows = [*(problems or []), *(active or [])]
        if counts is None and not rows:
            return None, []
        return self._summarise(counts, problems or [], active or [], capped), rows

    @staticmethod
    def _summarise(
        counts: dict[str, int] | None,
        problems: list[HatchetChildRun],
        active: list[HatchetChildRun],
        window_capped: bool = False,
    ) -> HatchetChildSummary:
        exact = counts is not None
        if counts is not None:
            truncated = len(problems) < counts["failed"] + counts["cancelled"] or len(active) < (
                counts["running"] + counts["queued"]
            )
        else:
            # No totals from the engine: count what was listed; a full page may hide more.
            rows = [*problems, *active]
            counts = {
                status: sum(1 for row in rows if row.status == status.upper())
                for status in _COUNT_KEYS
            }
            truncated = len(problems) >= _MAX_PROBLEM_ROWS or len(active) >= _MAX_ACTIVE_ROWS
        return HatchetChildSummary(
            total=sum(counts.values()),
            completed=counts["completed"],
            failed=counts["failed"],
            cancelled=counts["cancelled"],
            running=counts["running"],
            queued=counts["queued"],
            exact=exact,
            listed=len(problems) + len(active),
            truncated=truncated or window_capped,
        )

    async def _child_counts(
        self, spawning: list[Any], since: datetime, until: datetime
    ) -> dict[str, int] | None:
        """Exact group counts by status, summed over the spawning tasks; None if unknown."""
        if not spawning:
            return None
        totals = dict.fromkeys(_COUNT_KEYS, 0)
        try:
            for task in spawning:
                metrics = await _bounded(
                    hatchet.metrics.aio_get_task_metrics(
                        since=since, until=until, parent_task_external_id=task.task_external_id
                    )
                )
                for key in _COUNT_KEYS:
                    totals[key] += int(getattr(metrics, key))
        except Exception:
            logger.warning("Hatchet child metrics lookup failed", exc_info=True)
            return None
        return totals

    async def _list_children(
        self,
        run: WorkflowRunResponse,
        since: datetime,
        until: datetime,
        statuses: list[V1TaskStatus],
        limit: int,
    ) -> list[HatchetChildRun] | None:
        try:
            tasks = await _bounded(self._fetch_children(run, since, until, statuses, limit))
        except Exception:
            logger.warning("Hatchet child-run lookup failed run_id=%s", run.id, exc_info=True)
            return None
        return sorted((_child_info(t) for t in tasks), key=_child_sort_key)[:limit]

    @staticmethod
    async def _fetch_children(
        run: WorkflowRunResponse,
        since: datetime,
        until: datetime,
        statuses: list[V1TaskStatus],
        limit: int,
    ) -> list[Any]:
        kwargs: dict[str, Any] = {
            "since": since,
            "until": until,
            "additional_metadata": {"parent_run_id": str(run.id)},
            "statuses": statuses,
            "only_tasks": False,
            "limit": limit,
            "include_payloads": False,
        }
        if until - since < _PLAIN_LIST_WINDOW:
            return list((await hatchet.runs.aio_list(**kwargs)).rows or [])
        # A run that lasted a week or more: the SDK queries it one day at a time.
        return list(await hatchet.runs.aio_list_with_pagination(**kwargs))

    async def get_workers(self) -> HatchetWorkersResponse:
        try:
            listing = await _bounded(hatchet.workers.aio_list())
        except Exception:
            logger.warning("Hatchet worker listing failed", exc_info=True)
            return HatchetWorkersResponse(
                engine_reachable=False,
                message=_UNREACHABLE,
                missing_workers=list(EXPECTED_WORKERS),
            )

        rows = listing.rows or []
        workers = [self._worker_info(w) for w in rows]
        active_names = [w.name for w in rows if w.status == WorkerStatus.ACTIVE]
        missing = [
            expected
            for expected in EXPECTED_WORKERS
            if not any(_is_worker(expected, name) for name in active_names)
        ]
        return HatchetWorkersResponse(
            engine_reachable=True,
            message="OK",
            workers=workers,
            missing_workers=missing,
        )

    @staticmethod
    def _worker_info(worker: Any) -> HatchetWorkerInfo:
        slot_config = (worker.slot_config or {}).values()
        total = sum(c.limit for c in slot_config) if slot_config else None
        # ``available`` is optional in the API: one unset value makes the usage unknown.
        known = all(c.available is not None for c in slot_config)
        available = sum(c.available for c in slot_config) if slot_config and known else None
        return HatchetWorkerInfo(
            id=worker.metadata.id,
            name=worker.name,
            status=None if worker.status is None else _enum_value(worker.status),
            type=_enum_value(worker.type),
            last_heartbeat_at=worker.last_heartbeat_at,
            slots_used=None if total is None or available is None else total - available,
            slots_total=total,
            registered_workflows=[w.name for w in worker.registered_workflows or []],
        )
