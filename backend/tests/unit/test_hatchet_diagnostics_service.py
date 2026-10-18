"""Hatchet operator diagnostics: engine view of a run and worker health (SDK client mocked)."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hatchet_sdk.clients.rest.exceptions import NotFoundException
from hatchet_sdk.clients.rest.models.v1_task_event_type import V1TaskEventType
from hatchet_sdk.clients.rest.models.v1_task_status import V1TaskStatus
from hatchet_sdk.clients.rest.models.worker_status import WorkerStatus

from hatchet.dynamic_worker_config import DYNAMIC_WORKER_NAME
from hatchet.worker_config import WORKER_NAME
from services.hatchet import hatchet_diagnostics_service as svc
from services.hatchet.hatchet_diagnostics_service import (
    HatchetDiagnosticsService,
    status_mismatch,
)

# Well in the past, so the service's clamp to the real clock never changes the window.
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _run(
    status: str = "running",
    hatchet_run_id: str | None = "hr-1",
    finished_at: datetime | None = NOW + timedelta(hours=1),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        status=status,
        hatchet_run_id=hatchet_run_id,
        created_at=NOW,
        finished_at=finished_at,
    )


def _task(**kw: object) -> SimpleNamespace:
    base = {
        "display_name": "execute_steps",
        "status": V1TaskStatus.RUNNING,
        "attempt": 1,
        "retry_count": 0,
        "started_at": NOW,
        "finished_at": None,
        "duration": None,
        "error_message": None,
        "additional_metadata": {},
        "workflow_run_external_id": "child-1",
        "task_external_id": "task-1",
        "num_spawned_children": 0,
    }
    return SimpleNamespace(**{**base, **kw})


def _details(status: V1TaskStatus, tasks: list, events: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        run=SimpleNamespace(status=status), tasks=tasks, task_events=events or []
    )


def _worker(name: str, status: WorkerStatus = WorkerStatus.ACTIVE, **kw: object) -> SimpleNamespace:
    base = {
        "metadata": SimpleNamespace(id=f"id-{name}-{status.value}"),
        "name": name,
        "status": status,
        "type": SimpleNamespace(value="SELFHOSTED"),
        "last_heartbeat_at": NOW,
        "slot_config": {"default": SimpleNamespace(available=7, limit=10)},
        "registered_workflows": [SimpleNamespace(name="WorkflowExecution")],
    }
    return SimpleNamespace(**{**base, **kw})


def _metrics(**kw: int) -> SimpleNamespace:
    base = {"completed": 0, "failed": 0, "cancelled": 0, "running": 0, "queued": 0}
    return SimpleNamespace(**{**base, **kw})


def _group(index: int, status: V1TaskStatus) -> SimpleNamespace:
    return _task(
        display_name="execute_device_group",
        status=status,
        additional_metadata={"child_index": index},
        workflow_run_external_id=f"child-{index}",
    )


def _list_by_status(failed: list, active: list) -> AsyncMock:
    """aio_list stand-in: the problem query gets *failed*, the active query gets *active*."""

    async def _list(**kw: object) -> SimpleNamespace:
        statuses = kw["statuses"]
        return SimpleNamespace(rows=failed if V1TaskStatus.FAILED in statuses else active)

    return AsyncMock(side_effect=_list)


class StatusMismatchTests(unittest.TestCase):
    def test_agreement_is_not_flagged(self) -> None:
        self.assertIsNone(status_mismatch("running", "RUNNING"))
        self.assertIsNone(status_mismatch("success", "COMPLETED"))
        # A run that failed here can still end COMPLETED in the engine (failure handled).
        self.assertIsNone(status_mismatch("failed", "COMPLETED"))

    def test_active_here_terminal_in_engine(self) -> None:
        self.assertIn("reaper", status_mismatch("running", "FAILED") or "")

    def test_finished_here_live_in_engine(self) -> None:
        self.assertIn("still reports", status_mismatch("failed", "RUNNING") or "")

    def test_missing_in_engine_only_flags_active_runs(self) -> None:
        self.assertIsNotNone(status_mismatch("pending", None))
        self.assertIsNone(status_mismatch("success", None))


class RunDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        patcher = patch.object(svc, "hatchet", self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        link = patch.object(svc, "dashboard_run_url", return_value="http://hatchet/run/hr-1")
        link.start()
        self.addCleanup(link.stop)
        self.client.runs.aio_list = AsyncMock(return_value=SimpleNamespace(rows=[]))
        self.client.metrics.aio_get_task_metrics = AsyncMock(return_value=_metrics())

    async def test_never_dispatched_run_does_not_call_the_engine(self) -> None:
        result = await HatchetDiagnosticsService().get_run_diagnostics(
            _run(status="pending", hatchet_run_id=None)
        )
        self.assertTrue(result.engine_reachable)
        self.assertIsNotNone(result.mismatch)
        self.client.runs.aio_get.assert_not_called()

    async def test_maps_tasks_events_and_children(self) -> None:
        event = SimpleNamespace(
            task_display_name="execute_steps",
            event_type=V1TaskEventType.STARTED,
            timestamp=NOW,
            message="started",
            error_message=None,
            attempt=1,
        )
        self.client.runs.aio_get = AsyncMock(
            return_value=_details(V1TaskStatus.RUNNING, [_task()], [event])
        )
        child = _task(
            display_name="execute_device_group",
            status=V1TaskStatus.FAILED,
            additional_metadata={"child_index": 3},
            workflow_run_external_id="child-9",
        )
        self.client.runs.aio_list = AsyncMock(return_value=SimpleNamespace(rows=[child]))

        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())

        self.assertEqual(result.engine_status, "RUNNING")
        self.assertIsNone(result.mismatch)
        self.assertEqual(result.dashboard_url, "http://hatchet/run/hr-1")
        self.assertEqual(result.tasks[0].name, "execute_steps")
        self.assertEqual(result.events[0].event_type, "STARTED")
        self.assertEqual(result.child_runs[0].child_index, "3")
        self.assertIsNotNone(result.child_summary)
        for call in self.client.runs.aio_list.await_args_list:
            self.assertEqual(call.kwargs["additional_metadata"], {"parent_run_id": "42"})
            self.assertFalse(call.kwargs["include_payloads"])

    async def test_error_text_is_scrubbed_and_capped(self) -> None:
        long_error = "failed https://user:hunter2@git.example/x.git " + "x" * 5000
        self.client.runs.aio_get = AsyncMock(
            return_value=_details(V1TaskStatus.FAILED, [_task(error_message=long_error)])
        )
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run(status="failed"))
        error = result.tasks[0].error_message or ""
        self.assertNotIn("hunter2", error)
        self.assertLessEqual(len(error), 2001)

    async def test_mismatch_is_reported(self) -> None:
        self.client.runs.aio_get = AsyncMock(return_value=_details(V1TaskStatus.FAILED, []))
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run(status="running"))
        self.assertIsNotNone(result.mismatch)

    async def test_unknown_run_in_engine(self) -> None:
        self.client.runs.aio_get = AsyncMock(side_effect=NotFoundException(status=404))
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertTrue(result.engine_reachable)
        self.assertIn("no record", result.message)
        self.assertIsNotNone(result.mismatch)

    async def test_engine_down_never_leaks_exception_text(self) -> None:
        self.client.runs.aio_get = AsyncMock(side_effect=RuntimeError("token=hunter2 refused"))
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertFalse(result.engine_reachable)
        self.assertNotIn("hunter2", result.model_dump_json())

    async def test_child_lookup_failure_keeps_the_rest(self) -> None:
        self.client.runs.aio_get = AsyncMock(return_value=_details(V1TaskStatus.RUNNING, [_task()]))
        self.client.runs.aio_list = AsyncMock(side_effect=RuntimeError("boom"))
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertTrue(result.engine_reachable)
        self.assertEqual(result.child_runs, [])
        self.assertIsNone(result.child_summary)
        self.assertEqual(len(result.tasks), 1)

    def _fan_out(self, metrics: SimpleNamespace, failed: list, active: list) -> None:
        parent = _task(num_spawned_children=412, task_external_id="parent-task")
        self.client.runs.aio_get = AsyncMock(
            return_value=_details(V1TaskStatus.RUNNING, [_task(), parent])
        )
        self.client.metrics.aio_get_task_metrics = AsyncMock(return_value=metrics)
        self.client.runs.aio_list = _list_by_status(failed, active)

    async def test_counts_come_from_metrics_and_completed_groups_are_not_listed(self) -> None:
        self._fan_out(
            _metrics(completed=380, failed=1, running=2),
            failed=[_group(7, V1TaskStatus.FAILED)],
            active=[_group(9, V1TaskStatus.RUNNING), _group(8, V1TaskStatus.RUNNING)],
        )
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        summary = result.child_summary
        self.assertEqual((summary.total, summary.completed, summary.failed), (383, 380, 1))
        self.assertTrue(summary.exact)
        self.assertFalse(summary.truncated)
        self.assertEqual(summary.listed, 3)
        # Failed first, then running by group number.
        self.assertEqual([c.child_index for c in result.child_runs], ["7", "8", "9"])
        # Only tasks that spawned children are asked for metrics.
        self.client.metrics.aio_get_task_metrics.assert_awaited_once()
        kwargs = self.client.metrics.aio_get_task_metrics.await_args.kwargs
        self.assertEqual(kwargs["parent_task_external_id"], "parent-task")

    async def test_truncated_when_more_groups_failed_than_listed(self) -> None:
        self._fan_out(
            _metrics(completed=300, failed=112),
            failed=[_group(i, V1TaskStatus.FAILED) for i in range(100)],
            active=[],
        )
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertTrue(result.child_summary.truncated)
        self.assertEqual(result.child_summary.failed, 112)
        self.assertEqual(result.child_summary.listed, 100)

    async def test_metrics_failure_falls_back_to_listed_rows(self) -> None:
        self._fan_out(_metrics(), failed=[_group(1, V1TaskStatus.FAILED)], active=[])
        self.client.metrics.aio_get_task_metrics = AsyncMock(side_effect=RuntimeError("down"))
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertFalse(result.child_summary.exact)
        self.assertEqual(result.child_summary.failed, 1)
        self.assertEqual(result.child_summary.completed, 0)

    async def test_no_spawning_task_skips_metrics(self) -> None:
        self.client.runs.aio_get = AsyncMock(return_value=_details(V1TaskStatus.RUNNING, [_task()]))
        self.client.runs.aio_list = _list_by_status([], [])
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.client.metrics.aio_get_task_metrics.assert_not_called()
        self.assertIsNone(result.child_summary)
        self.assertEqual(result.child_runs, [])

    async def test_one_failing_list_keeps_the_other_bucket(self) -> None:
        self._fan_out(_metrics(failed=1, running=1), failed=[], active=[])

        async def _list(**kw: object) -> SimpleNamespace:
            if V1TaskStatus.FAILED in kw["statuses"]:
                raise RuntimeError("boom")
            return SimpleNamespace(rows=[_group(2, V1TaskStatus.RUNNING)])

        self.client.runs.aio_list = AsyncMock(side_effect=_list)
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertEqual([c.child_index for c in result.child_runs], ["2"])
        self.assertTrue(result.child_summary.truncated)

    async def test_events_truncated_flag(self) -> None:
        event = SimpleNamespace(
            task_display_name="t",
            event_type=V1TaskEventType.STARTED,
            timestamp=NOW,
            message="m",
            error_message=None,
            attempt=1,
        )
        self.client.runs.aio_get = AsyncMock(
            return_value=_details(V1TaskStatus.RUNNING, [_task()], [event] * 201)
        )
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertTrue(result.events_truncated)
        self.assertEqual(len(result.events), 200)


class LongRunTests(unittest.IsolatedAsyncioTestCase):
    """Groups spawned long after the run was created must still be counted."""

    def setUp(self) -> None:
        self.client = MagicMock()
        patcher = patch.object(svc, "hatchet", self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        link = patch.object(svc, "dashboard_run_url", return_value=None)
        link.start()
        self.addCleanup(link.stop)
        parent = _task(num_spawned_children=3, task_external_id="parent-task")
        self.client.runs.aio_get = AsyncMock(return_value=_details(V1TaskStatus.RUNNING, [parent]))
        self.client.metrics.aio_get_task_metrics = AsyncMock(return_value=_metrics(completed=3))
        self.client.runs.aio_list = AsyncMock(return_value=SimpleNamespace(rows=[]))
        self.client.runs.aio_list_with_pagination = AsyncMock(return_value=[])

    async def test_window_follows_the_runs_whole_span(self) -> None:
        finished = NOW + timedelta(days=9)
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run(finished_at=finished))
        kwargs = self.client.metrics.aio_get_task_metrics.await_args.kwargs
        self.assertEqual(kwargs["since"], NOW)
        self.assertGreaterEqual(kwargs["until"], finished)
        # A span of a week or more is queried through the SDK's per-day pagination.
        self.client.runs.aio_list.assert_not_called()
        self.assertEqual(self.client.runs.aio_list_with_pagination.await_count, 2)
        self.assertFalse(result.child_summary.truncated)

    async def test_short_run_uses_the_plain_list(self) -> None:
        await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.client.runs.aio_list_with_pagination.assert_not_called()
        self.assertEqual(self.client.runs.aio_list.await_count, 2)

    async def test_span_beyond_the_cap_is_marked_truncated(self) -> None:
        finished = NOW + timedelta(days=45)
        result = await HatchetDiagnosticsService().get_run_diagnostics(_run(finished_at=finished))
        kwargs = self.client.metrics.aio_get_task_metrics.await_args.kwargs
        self.assertEqual(kwargs["until"], NOW + timedelta(days=30))
        self.assertTrue(result.child_summary.truncated)

    async def test_unresponsive_engine_is_cut_off(self) -> None:
        async def _hang(*_a: object, **_k: object) -> None:
            await asyncio.sleep(60)

        self.client.runs.aio_get = _hang
        with patch.object(svc, "_ENGINE_TIMEOUT_SECONDS", 0.05):
            result = await HatchetDiagnosticsService().get_run_diagnostics(_run())
        self.assertFalse(result.engine_reachable)


class WorkersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.config.namespace = ""
        patcher = patch.object(svc, "hatchet", self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_all_expected_workers_active(self) -> None:
        rows = [_worker(WORKER_NAME), _worker(DYNAMIC_WORKER_NAME)]
        self.client.workers.aio_list = AsyncMock(return_value=SimpleNamespace(rows=rows))
        result = await HatchetDiagnosticsService().get_workers()
        self.assertEqual(result.missing_workers, [])
        self.assertEqual(result.workers[0].slots_used, 3)
        self.assertEqual(result.workers[0].slots_total, 10)
        self.assertEqual(result.workers[0].registered_workflows, ["WorkflowExecution"])

    async def test_inactive_or_absent_worker_is_missing(self) -> None:
        rows = [_worker(WORKER_NAME), _worker(DYNAMIC_WORKER_NAME, status=WorkerStatus.INACTIVE)]
        self.client.workers.aio_list = AsyncMock(return_value=SimpleNamespace(rows=rows))
        result = await HatchetDiagnosticsService().get_workers()
        self.assertEqual(result.missing_workers, [DYNAMIC_WORKER_NAME])

    async def test_same_name_rows_keep_distinct_ids(self) -> None:
        rows = [_worker(WORKER_NAME), _worker(WORKER_NAME, status=WorkerStatus.INACTIVE)]
        self.client.workers.aio_list = AsyncMock(return_value=SimpleNamespace(rows=rows))
        result = await HatchetDiagnosticsService().get_workers()
        self.assertEqual(len({w.id for w in result.workers}), 2)

    async def test_a_debug_copy_does_not_hide_a_dead_worker(self) -> None:
        rows = [
            _worker(f"{WORKER_NAME}-debug"),
            _worker(WORKER_NAME, status=WorkerStatus.INACTIVE),
            _worker(DYNAMIC_WORKER_NAME),
        ]
        self.client.workers.aio_list = AsyncMock(return_value=SimpleNamespace(rows=rows))
        result = await HatchetDiagnosticsService().get_workers()
        self.assertEqual(result.missing_workers, [WORKER_NAME])

    async def test_namespace_prefix_is_ignored(self) -> None:
        self.client.config.namespace = "dev_"
        rows = [_worker(f"dev_{WORKER_NAME}"), _worker(f"dev_{DYNAMIC_WORKER_NAME}")]
        self.client.workers.aio_list = AsyncMock(return_value=SimpleNamespace(rows=rows))
        result = await HatchetDiagnosticsService().get_workers()
        self.assertEqual(result.missing_workers, [])

    async def test_unset_available_slots_do_not_fail_the_listing(self) -> None:
        unknown = _worker(
            WORKER_NAME, slot_config={"default": SimpleNamespace(available=None, limit=10)}
        )
        self.client.workers.aio_list = AsyncMock(
            return_value=SimpleNamespace(rows=[unknown, _worker(DYNAMIC_WORKER_NAME)])
        )
        result = await HatchetDiagnosticsService().get_workers()
        self.assertTrue(result.engine_reachable)
        self.assertEqual(result.workers[0].slots_total, 10)
        self.assertIsNone(result.workers[0].slots_used)
        self.assertEqual(result.workers[1].slots_used, 3)

    async def test_engine_down(self) -> None:
        self.client.workers.aio_list = AsyncMock(side_effect=ConnectionError("down"))
        result = await HatchetDiagnosticsService().get_workers()
        self.assertFalse(result.engine_reachable)
        self.assertEqual(len(result.missing_workers), 2)


if __name__ == "__main__":
    unittest.main()
