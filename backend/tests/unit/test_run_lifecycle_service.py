"""CF-01 steps 2 and 7: fail_interrupted and the reaper."""

from __future__ import annotations

import asyncio
import unittest
import unittest.mock
from datetime import timedelta

from repositories.run_repository import RunRepository
from services.execution.run_lifecycle_service import RunLifecycleService
from tests.unit.test_run_repository_transitions import add_run, make_db


class RunLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        engine, self.db = make_db()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.repo = RunRepository(self.db)
        self.service = RunLifecycleService(self.db)

    def test_fail_interrupted_finalises_steps(self) -> None:
        run = add_run(self.db)
        step = self.repo.create_step_result(
            run_id=run.id, step_node_id="a", step_type="x", step_name="a"
        )
        step.status = "running"
        self.db.commit()
        self.assertTrue(self.service.fail_interrupted(run.id, message="lost"))
        self.db.refresh(run)
        self.db.refresh(step)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "lost")
        self.assertTrue(run.error_id)
        self.assertEqual(step.status, "failed")

    def test_fail_interrupted_cancels_the_active_child_runs(self) -> None:
        parent = add_run(self.db, uuid="p")
        active = add_run(self.db, uuid="c1")
        active.parent_run_id = parent.id
        done = add_run(self.db, status="success", uuid="c2")
        done.parent_run_id = parent.id
        self.db.commit()

        self.assertTrue(self.service.fail_interrupted(parent.id, message="lost"))

        for run in (parent, active, done):
            self.db.refresh(run)
        self.assertEqual(parent.status, "failed")
        self.assertEqual(active.status, "cancelled")
        self.assertEqual(done.status, "success")

    def test_a_failing_child_cancel_never_blocks_finalising_the_parent(self) -> None:
        parent = add_run(self.db, uuid="p")
        with unittest.mock.patch(
            "services.execution.run_service.RunService.cancel_child_runs",
            side_effect=RuntimeError("engine down"),
        ):
            self.assertTrue(self.service.fail_interrupted(parent.id, message="lost"))
        self.db.refresh(parent)
        self.assertEqual(parent.status, "failed")

    def test_fail_interrupted_does_not_touch_cancelled_run(self) -> None:
        run = add_run(self.db, status="cancelled")
        self.assertFalse(self.service.fail_interrupted(run.id, message="lost"))
        self.db.refresh(run)
        self.assertEqual(run.status, "cancelled")
        self.assertIsNone(run.error_message)

    def _reap(self, run_status: str | None, grace=timedelta(0), hatchet_run_id="h1"):
        run = add_run(self.db, status="running", hatchet_run_id=hatchet_run_id)

        async def engine_status(_: str) -> str | None:
            return run_status

        reaped = asyncio.run(self.service.reap_stuck_runs(grace=grace, engine_status=engine_status))
        self.db.refresh(run)
        return reaped, run

    def test_reaper_fails_run_whose_engine_run_failed(self) -> None:
        reaped, run = self._reap("FAILED")
        self.assertEqual((reaped, run.status), (1, "failed"))

    def test_reaper_leaves_run_the_engine_still_runs(self) -> None:
        reaped, run = self._reap("RUNNING")
        self.assertEqual((reaped, run.status), (0, "running"))

    def test_reaper_skips_when_engine_unreachable(self) -> None:
        reaped, run = self._reap(None)
        self.assertEqual((reaped, run.status), (0, "running"))

    def test_reaper_fails_pending_run_without_engine_id(self) -> None:
        run = add_run(self.db, status="pending", hatchet_run_id=None)

        async def engine_status(_: str) -> str | None:
            raise AssertionError("must not be asked")

        reaped = asyncio.run(
            self.service.reap_stuck_runs(grace=timedelta(0), engine_status=engine_status)
        )
        self.db.refresh(run)
        self.assertEqual((reaped, run.status), (1, "failed"))

    def test_reaper_respects_grace_period(self) -> None:
        reaped, run = self._reap("FAILED", grace=timedelta(hours=1))
        self.assertEqual((reaped, run.status), (0, "running"))


if __name__ == "__main__":
    unittest.main()
