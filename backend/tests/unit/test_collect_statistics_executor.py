"""Tests for collect-statistics executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import DeviceContext, WorkflowContext
from workflow_steps.collect_statistics.executor import execute


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    run.workflow_id = 42
    return run


def _workflow() -> MagicMock:
    workflow = MagicMock()
    workflow.id = 42
    workflow.name = "Get Backups"
    return workflow


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _patches(*, workflow_result=None, job_statistics_repo=None):
    workflow_repo = MagicMock()
    workflow_repo.get_by_id.return_value = workflow_result
    repo_instance = job_statistics_repo or MagicMock()
    return (
        patch(
            "workflow_steps.common.notification_context.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "workflow_steps.common.notification_context.WorkflowRepository",
            return_value=workflow_repo,
        ),
        patch(
            "workflow_steps.collect_statistics.executor.JobStatisticsRepository",
            return_value=repo_instance,
        ),
    )


class CollectStatisticsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_one_row_per_device_with_configured_result(self) -> None:
        device1 = DeviceContext(id="d1", name="router1", hostname="router1")
        device2 = DeviceContext(id="d2", name="router2", hostname="router2")
        context = _context({"d1": device1, "d2": device2})

        repo = MagicMock()
        repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, repo_p = _patches(
            workflow_result=(_workflow(), "alice"),
            job_statistics_repo=repo,
        )
        with session_p, workflow_p, repo_p:
            outcomes = await execute(
                config={"result": "failed"},
                context=context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="collect-statistics-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertIs(outcomes[0].context, context)

        rows = repo.create_batch.call_args.args[0]
        self.assertEqual(len(rows), 2)
        names = {row["device_name"] for row in rows}
        self.assertEqual(names, {"router1", "router2"})
        for row in rows:
            self.assertEqual(row["run_id"], 1)
            self.assertEqual(row["node_id"], "collect-statistics-1")
            self.assertEqual(row["workflow_id"], 42)
            self.assertEqual(row["workflow_name"], "Get Backups")
            self.assertEqual(row["result"], "failed")

    async def test_two_instances_record_disjoint_results(self) -> None:
        """Simulates the success-node + failure-node wiring pattern."""
        device1 = DeviceContext(id="d1", name="router1", hostname="router1")
        device2 = DeviceContext(id="d2", name="router2", hostname="router2")
        success_context = _context({"d1": device1})
        failed_context = _context({"d2": device2})

        repo = MagicMock()
        repo.create_batch.side_effect = lambda rows: [MagicMock() for _ in rows]

        session_p, workflow_p, repo_p = _patches(
            workflow_result=(_workflow(), "alice"),
            job_statistics_repo=repo,
        )
        with session_p, workflow_p, repo_p:
            await execute(
                config={"result": "success"},
                context=success_context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="collect-statistics-success",
                device_sessions=MagicMock(),
            )
            await execute(
                config={"result": "failed"},
                context=failed_context,
                run=_run(),
                artifact_service=MagicMock(),
                node_id="collect-statistics-failed",
                device_sessions=MagicMock(),
            )

        all_rows = [row for call in repo.create_batch.call_args_list for row in call.args[0]]
        results_by_device = {row["device_name"]: row["result"] for row in all_rows}
        self.assertEqual(results_by_device, {"router1": "success", "router2": "failed"})

    async def test_invalid_result_raises(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"result": "maybe"},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="collect-statistics-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_result_raises(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="collect-statistics-1",
                device_sessions=MagicMock(),
            )

    async def test_no_devices_short_circuits_without_db_access(self) -> None:
        repo = MagicMock()

        session_p, workflow_p, repo_p = _patches(job_statistics_repo=repo)
        with session_p, workflow_p, repo_p:
            outcomes = await execute(
                config={"result": "success"},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="collect-statistics-1",
                device_sessions=MagicMock(),
            )

        repo.create_batch.assert_not_called()
        self.assertEqual(outcomes[0].name, "success")

    async def test_missing_db_session_raises_runtime_error(self) -> None:
        with patch("workflow_steps.common.notification_context.object_session", return_value=None):
            device = DeviceContext(id="d1", name="router1", hostname="router1")
            with self.assertRaises(RuntimeError):
                await execute(
                    config={"result": "success"},
                    context=_context({"d1": device}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="collect-statistics-1",
                    device_sessions=MagicMock(),
                )

    async def test_workflow_not_found_raises_value_error(self) -> None:
        device = DeviceContext(id="d1", name="router1", hostname="router1")
        session_p, workflow_p, repo_p = _patches(workflow_result=None)
        with session_p, workflow_p, repo_p:
            with self.assertRaises(ValueError):
                await execute(
                    config={"result": "success"},
                    context=_context({"d1": device}),
                    run=_run(),
                    artifact_service=MagicMock(),
                    node_id="collect-statistics-1",
                    device_sessions=MagicMock(),
                )


if __name__ == "__main__":
    unittest.main()
