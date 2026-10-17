"""S2-03: only the person who started a run may cancel it, approve its batches or delete it."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import AccessDeniedError, ValidationFailedError
from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from services.auth.rbac_service import RBACService
from services.execution.run_service import RunService

OWNER, OTHER, CREATOR = 1, 2, 3


class RunControlTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowRunDeviceGroup.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        workflow = Workflow(name="wf", creator_id=CREATOR, visibility="public")
        self.db.add(workflow)
        self.db.commit()
        self.workflow = workflow
        self.service = RunService(self.db)
        hatchet = patch("hatchet.client.hatchet", new=MagicMock())
        self.hatchet = hatchet.start()
        self.addCleanup(hatchet.stop)
        self._admins: set[int] = set()
        role = patch.object(
            RBACService,
            "has_role",
            lambda _self, uid, name: name == "admin" and uid in self._admins,
        )
        role.start()
        self.addCleanup(role.stop)

    def _run(self, **kw) -> WorkflowRun:
        defaults = dict(
            uuid="u1",
            workflow_id=self.workflow.id,
            triggered_by_id=OWNER,
            status="running",
            trigger_type="manual",
            device_ids=[],
        )
        defaults.update(kw)
        run = WorkflowRun(**defaults)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def test_progress_contains_no_step_output(self) -> None:
        run = self._run(status="running", current_node_id="n2")
        big = {"outcomes": {"success": {"blob": "x" * 2_000_000}}}
        self.db.add_all(
            [
                WorkflowStepResult(
                    run_id=run.id,
                    step_node_id="n1",
                    step_type="x",
                    step_name="one",
                    status="success",
                    output=big,
                ),
                WorkflowStepResult(
                    run_id=run.id,
                    step_node_id="n2",
                    step_type="x",
                    step_name="two",
                    status="failed",
                    error_message="boom",
                ),
            ]
        )
        self.db.commit()

        progress = self.service.get_run_progress(run.id, OWNER)

        payload = progress.model_dump_json()
        self.assertLess(len(payload), 5_000)
        self.assertNotIn("blob", payload)
        self.assertEqual(progress.status, "running")
        self.assertEqual(progress.current_node_id, "n2")
        self.assertEqual(
            [(s.step_node_id, s.status, s.has_error) for s in progress.steps],
            [("n1", "success", False), ("n2", "failed", True)],
        )

    def test_progress_respects_workflow_visibility(self) -> None:
        self.workflow.visibility = "private"
        self.db.commit()
        run = self._run()
        with self.assertRaises(AccessDeniedError):
            self.service.get_run_progress(run.id, OTHER)
        self.assertEqual(self.service.get_run_progress(run.id, CREATOR).id, run.id)

    def test_other_user_cannot_cancel_run_of_public_workflow(self) -> None:
        run = self._run()
        with self.assertRaises(AccessDeniedError):
            self.service.cancel_run(run.id, OTHER)
        self.hatchet.runs.cancel.assert_not_called()

    def test_other_user_cannot_approve_batch_or_approve_all(self) -> None:
        run = self._run(status="paused", approval_state={"awaiting": True, "next_batch_index": 1})
        with self.assertRaises(AccessDeniedError):
            self.service.approve_batch(run.id, OTHER)
        with self.assertRaises(AccessDeniedError):
            self.service.approve_all(run.id, OTHER)
        self.hatchet.event.push.assert_not_called()

    def test_other_user_cannot_delete_finished_run(self) -> None:
        run = self._run(status="success")
        with self.assertRaises(AccessDeniedError):
            self.service.delete_run(run.id, OTHER)

    def test_admin_can_cancel_and_delete_but_not_approve(self) -> None:
        self._admins.add(OTHER)
        running = self._run()
        with self.assertLogs("services.execution.run_service", level=logging.WARNING) as logs:
            self.service.cancel_run(running.id, OTHER)
        self.assertTrue(any("run_control_admin_override" in m for m in logs.output))
        done = self._run(uuid="u2", status="success")
        self.service.delete_run(done.id, OTHER)
        paused = self._run(
            uuid="u3", status="paused", approval_state={"awaiting": True, "next_batch_index": 1}
        )
        with self.assertRaises(AccessDeniedError):
            self.service.approve_batch(paused.id, OTHER)

    def test_orphan_run_belongs_to_workflow_creator(self) -> None:
        run = self._run(triggered_by_id=None)
        with self.assertRaises(AccessDeniedError):
            self.service.cancel_run(run.id, OTHER)
        self.service.cancel_run(run.id, CREATOR)

    def test_orphan_run_without_creator_is_admin_only(self) -> None:
        self.workflow.creator_id = None
        self.db.commit()
        run = self._run(triggered_by_id=None)
        with self.assertRaises(AccessDeniedError):
            self.service.cancel_run(run.id, OTHER)
        self._admins.add(OTHER)
        self.service.cancel_run(run.id, OTHER)

    def test_cancel_marks_cancelled_even_when_hatchet_raises(self) -> None:
        run = self._run(hatchet_run_id="h1")
        step = WorkflowStepResult(
            run_id=run.id, step_node_id="a", step_type="x", step_name="a", status="running"
        )
        self.db.add(step)
        self.db.commit()
        self.hatchet.runs.cancel.side_effect = RuntimeError("engine down")
        self.service.cancel_run(run.id, OWNER)
        self.db.refresh(run)
        self.db.refresh(step)
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(step.status, "failed")
        self.assertIn("engine could not be reached", run.debug_message or "")
        # A worker that finishes anyway cannot flip the row back (C1-03).
        from repositories.run_repository import RunRepository

        RunRepository(self.db).update_run_status(run, status="success")
        self.assertEqual(run.status, "cancelled")

    def test_list_runs_is_paged_and_reports_total(self) -> None:
        for index in range(120):
            self._run(uuid=f"page-{index}", status="success")
        first = self.service.list_runs(self.workflow.id, OWNER)
        self.assertEqual(len(first.runs), 50)
        self.assertEqual(first.total, 120)
        self.assertEqual((first.limit, first.offset), (50, 0))
        last = self.service.list_runs(self.workflow.id, OWNER, offset=100)
        self.assertEqual(len(last.runs), 20)
        self.assertEqual(last.total, 120)
        ids = [r.id for r in first.runs] + [
            r.id for r in self.service.list_runs(self.workflow.id, OWNER, offset=50).runs
        ]
        self.assertEqual(len(set(ids)), 100)

    def test_list_runs_total_respects_status_filter(self) -> None:
        for index in range(3):
            self._run(uuid=f"ok-{index}", status="success")
        self._run(uuid="bad", status="failed")
        page = self.service.list_runs(self.workflow.id, OWNER, statuses=["failed"], limit=1)
        self.assertEqual((len(page.runs), page.total), (1, 1))

    def test_cancel_of_finished_run_is_refused(self) -> None:
        run = self._run(status="success")
        with self.assertRaises(ValidationFailedError):
            self.service.cancel_run(run.id, OWNER)


if __name__ == "__main__":
    unittest.main()
