"""CF-01 step 1: terminal run states are sticky (compare-and-set)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from repositories.run_repository import RunRepository, StepResultExistsError


def make_db():
    engine = create_engine("sqlite:///:memory:")
    WorkflowRun.metadata.create_all(
        engine, tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__]
    )
    return engine, sessionmaker(bind=engine)()


def add_run(db, status="running", workflow_id=1, hatchet_run_id=None, uuid="u1"):
    run = WorkflowRun(
        uuid=uuid,
        workflow_id=workflow_id,
        triggered_by_id=None,
        status=status,
        trigger_type="manual",
        device_ids=[],
        hatchet_run_id=hatchet_run_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


class RunTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        engine, self.db = make_db()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.repo = RunRepository(self.db)

    def test_terminal_status_is_never_overwritten(self) -> None:
        run = add_run(self.db)
        self.assertTrue(self.repo.transition_run(run.id, to_status="cancelled"))
        result = self.repo.update_run_status(
            run, status="success", finished_at=datetime(2030, 1, 1, tzinfo=UTC)
        )
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.finished_at)

    def test_recording_hatchet_id_never_reverts_a_claimed_run(self) -> None:
        # The worker's prepare task can claim the run before the API stores the Hatchet id.
        run = add_run(self.db, status="pending")
        self.assertTrue(
            self.repo.transition_run(run.id, to_status="running", from_statuses=("pending",))
        )
        result = self.repo.record_hatchet_run_id(run, "h-1")
        self.assertEqual(result.status, "running")
        self.assertEqual(result.hatchet_run_id, "h-1")

    def test_recording_hatchet_id_on_a_pending_run_keeps_it_pending(self) -> None:
        run = add_run(self.db, status="pending")
        result = self.repo.record_hatchet_run_id(run, "h-2")
        self.assertEqual((result.status, result.hatchet_run_id), ("pending", "h-2"))

    def test_claim_only_from_pending(self) -> None:
        run = add_run(self.db, status="running")
        self.assertFalse(
            self.repo.transition_run(run.id, to_status="running", from_statuses=("pending",))
        )
        pending = add_run(self.db, status="pending", uuid="u2")
        self.assertTrue(
            self.repo.transition_run(pending.id, to_status="running", from_statuses=("pending",))
        )

    def test_finalise_open_step_results(self) -> None:
        run = add_run(self.db)
        rows = {}
        for node, status in (("a", "running"), ("b", "pending"), ("c", "success")):
            row = self.repo.create_step_result(
                run_id=run.id, step_node_id=node, step_type="x", step_name=node
            )
            row.status = status
            rows[node] = row
        self.db.commit()
        self.repo.finalise_open_step_results(run.id, message="boom")
        for row in rows.values():
            self.db.refresh(row)
        self.assertEqual(
            (rows["a"].status, rows["b"].status, rows["c"].status),
            ("failed", "skipped", "success"),
        )
        self.assertEqual(rows["a"].error_message, "boom")

    def test_late_success_does_not_reopen_a_step_closed_by_cancel(self) -> None:
        run = add_run(self.db)
        step = self.repo.create_step_result(
            run_id=run.id, step_node_id="a", step_type="x", step_name="a"
        )
        self.repo.update_step_result(step, status="running")
        self.repo.transition_run(run.id, to_status="cancelled")
        self.repo.finalise_open_step_results(run.id, message="Cancelled by the operator")
        self.repo.update_step_result(step, status="success", output={"outcomes": {}})
        self.assertEqual(step.status, "failed")
        self.assertIsNone(step.output)

    def test_terminal_step_may_still_be_updated_on_a_live_run(self) -> None:
        # fan-out aggregation writes a node twice (partial, then final)
        run = add_run(self.db)
        step = self.repo.create_step_result(
            run_id=run.id, step_node_id="a", step_type="x", step_name="a"
        )
        self.repo.update_step_result(step, status="failed")
        self.repo.update_step_result(step, status="success")
        self.assertEqual(step.status, "success")

    def test_second_row_for_the_same_node_is_refused(self) -> None:
        run = add_run(self.db)
        self.repo.create_step_result(run_id=run.id, step_node_id="a", step_type="x", step_name="a")
        with self.assertRaises(StepResultExistsError):
            self.repo.create_step_result(
                run_id=run.id, step_node_id="a", step_type="x", step_name="a"
            )
        # the session is usable afterwards
        self.repo.create_step_result(run_id=run.id, step_node_id="b", step_type="x", step_name="b")

    def test_has_active_runs(self) -> None:
        add_run(self.db, status="success", workflow_id=7)
        self.assertFalse(self.repo.has_active_runs(7))
        add_run(self.db, status="paused", workflow_id=7, uuid="u3")
        self.assertTrue(self.repo.has_active_runs(7))


if __name__ == "__main__":
    unittest.main()
