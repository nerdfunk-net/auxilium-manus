"""CF-01 steps 3-4: the Hatchet task never leaves the run row open."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from hatchet.workflows import workflow_run as wf_run
from repositories.run_repository import RunRepository
from services.execution.step_runner import RunAlreadyStarted
from tests.unit.test_run_repository_transitions import add_run, make_db


def _fn(task):
    return getattr(task, "_fn", None) or getattr(task, "fn", task)


class WorkflowRunLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        engine, self.db = make_db()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        factory = MagicMock()
        factory.return_value.__enter__.return_value = self.db
        factory.return_value.__exit__.return_value = False
        patcher = patch("core.database.SessionLocal", factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _execute(self, run, side_effect):
        inp = wf_run.WorkflowRunInput(run_id=run.id)
        with patch.object(wf_run, "_execute_steps", side_effect=side_effect):
            return asyncio.run(wf_run.execute_steps(inp, MagicMock()))

    def test_marks_run_failed_when_walk_raises_without_leaking_text(self) -> None:
        run = add_run(self.db)
        with self.assertRaises(RuntimeError):
            self._execute(run, RuntimeError("password=hunter2"))
        self.db.refresh(run)
        self.assertEqual(run.status, "failed")
        self.assertTrue(run.error_id)
        self.assertEqual(run.error_message, wf_run._INTERNAL)
        self.assertNotIn("hunter2", run.error_message)

    def test_marks_failed_on_cancelled_error(self) -> None:
        run = add_run(self.db)
        with self.assertRaises(asyncio.CancelledError):
            self._execute(run, asyncio.CancelledError())
        self.db.refresh(run)
        self.assertEqual((run.status, run.error_message), ("failed", wf_run._INTERRUPTED))

    def test_redelivered_run_is_failed_with_fixed_message(self) -> None:
        run = add_run(self.db)
        with self.assertRaises(RunAlreadyStarted):
            self._execute(run, RunAlreadyStarted("x"))
        self.db.refresh(run)
        self.assertEqual((run.status, run.error_message), ("failed", wf_run._DELIVERED_TWICE))

    def test_cancelled_run_stays_cancelled_after_worker_error(self) -> None:
        run = add_run(self.db, status="cancelled")
        with self.assertRaises(RuntimeError):
            self._execute(run, RuntimeError("late"))
        self.db.refresh(run)
        self.assertEqual(run.status, "cancelled")

    def test_prepare_does_not_start_a_cancelled_run(self) -> None:
        run = add_run(self.db, status="cancelled")
        out = asyncio.run(_fn(wf_run.prepare)(wf_run.WorkflowRunInput(run_id=run.id), MagicMock()))
        self.db.refresh(run)
        self.assertFalse(out["claimed"])
        self.assertEqual(run.status, "cancelled")

    def test_prepare_claims_a_pending_run(self) -> None:
        run = add_run(self.db, status="pending")
        out = asyncio.run(_fn(wf_run.prepare)(wf_run.WorkflowRunInput(run_id=run.id), MagicMock()))
        self.db.refresh(run)
        self.assertTrue(out["claimed"])
        self.assertEqual(run.status, "running")
        self.assertIsNotNone(run.started_at)

    def test_fail_run_task_finalises_an_active_run(self) -> None:
        run = add_run(self.db)
        asyncio.run(wf_run.fail_run(wf_run.WorkflowRunInput(run_id=run.id), MagicMock()))
        self.db.refresh(run)
        self.assertEqual(run.status, "failed")

    def test_replay_of_finished_run_is_noop(self) -> None:
        run = add_run(self.db, status="success")
        asyncio.run(wf_run.fail_run(wf_run.WorkflowRunInput(run_id=run.id), MagicMock()))
        self.db.refresh(run)
        self.assertEqual(run.status, "success")

    def test_second_execute_all_does_not_run_steps_again(self) -> None:
        from services.execution.step_runner import StepRunner

        run = add_run(self.db)
        RunRepository(self.db).create_step_result(
            run_id=run.id, step_node_id="a", step_type="x", step_name="a"
        )
        runner = StepRunner(self.db)
        wf = MagicMock()
        with patch.object(runner, "load_execution_graph", return_value=([], [])):
            with self.assertRaises(RunAlreadyStarted):
                asyncio.run(runner.execute_all(run=run, workflow=wf))

    def test_lost_insert_race_is_reported_as_already_started(self) -> None:
        from repositories.run_repository import StepResultExistsError
        from services.execution.step_runner import StepRunner

        run = add_run(self.db)
        runner = StepRunner(self.db)
        with (
            patch.object(runner, "load_execution_graph", return_value=([], [])),
            patch.object(
                runner,
                "create_pending_step_results",
                side_effect=StepResultExistsError("duplicate"),
            ),
        ):
            with self.assertRaises(RunAlreadyStarted):
                asyncio.run(runner.execute_all(run=run, workflow=MagicMock()))


if __name__ == "__main__":
    unittest.main()
