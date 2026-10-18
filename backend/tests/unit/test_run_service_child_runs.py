"""Child runs: a run started by a step of another run (start-workflow).

* the child records `parent_run_id`; devices reach it only as a declared run input;
* it runs as the parent's triggering user, who needs ``workflows:execute`` and access;
* a workflow can never (transitively) start itself, and the chain is depth-limited;
* cancelling the parent cancels its still-active children.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import AccessDeniedError, NotFoundError, ValidationFailedError
from core.models.background_tier import WorkflowBackgroundTier
from core.models.runs import WorkflowRun, WorkflowRunDeviceGroup, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.workflow_validation import WorkflowValidationResult
from services.auth.rbac_service import RBACService
from services.execution.dispatch_breaker import DispatchBreaker
from services.execution.run_service import MAX_CHILD_RUN_DEPTH, RunService

OWNER, OTHER = 1, 2


class ChildRunTests(unittest.TestCase):
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
                WorkflowBackgroundTier.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = RunService(self.db)

        for target, kwargs in (
            ("services.execution.run_service.dispatch_breaker", {"new": DispatchBreaker()}),
            ("services.execution.run_service.WorkflowValidationService", {}),
        ):
            started = patch(target, **kwargs).start()
            self.addCleanup(patch.stopall)
            if "Validation" in target:
                started.return_value.validate.return_value = WorkflowValidationResult(
                    findings=[], has_errors=False
                )
        self.dispatch = patch(
            "hatchet.workflows.workflow_run.workflow.run_no_wait",
            return_value=MagicMock(workflow_run_id="hatchet-child"),
        ).start()
        self.hatchet = patch("hatchet.client.hatchet", new=MagicMock()).start()

        self.allowed = True
        patch.object(
            RBACService, "has_permission", lambda _self, uid, res, act: self.allowed
        ).start()
        patch.object(RBACService, "has_role", lambda _self, uid, name: False).start()

        self.parent_wf = self._workflow("backup-trigger")
        self.child_wf = self._workflow("backup")
        self.parent = self._run(self.parent_wf, triggered_by_id=OWNER, status="running")

    def _workflow(self, name: str, **kw) -> Workflow:
        defaults = {"name": name, "creator_id": OWNER, "visibility": "public"}
        defaults.update(kw)
        wf = Workflow(**defaults)
        self.db.add(wf)
        self.db.commit()
        return wf

    def _run(self, workflow: Workflow, **kw) -> WorkflowRun:
        defaults = {
            "uuid": f"u{self.db.query(WorkflowRun).count() + 1}",
            "workflow_id": workflow.id,
            "triggered_by_id": OWNER,
            "status": "running",
            "trigger_type": "manual",
            "device_ids": [],
        }
        defaults.update(kw)
        run = WorkflowRun(**defaults)
        self.db.add(run)
        self.db.commit()
        return run

    def _start(self, parent=None, workflow=None, **kw) -> WorkflowRun:
        return self.service.start_child_run(
            parent or self.parent,
            (workflow or self.child_wf).id,
            run_inputs=kw.get("run_inputs", {}),
        )

    def test_child_records_its_parent_and_trigger_type(self) -> None:
        child = self._start()
        self.assertEqual(child.parent_run_id, self.parent.id)
        self.assertEqual(child.trigger_type, "workflow")
        self.assertEqual(child.triggered_by_id, OWNER)
        self.assertEqual((child.status, child.hatchet_run_id), ("pending", "hatchet-child"))

    def test_run_inputs_are_resolved_against_the_child_schema(self) -> None:
        self.child_wf.static_attributes = [
            {"name": "note", "type": "string", "default": "x", "required": True}
        ]
        self.db.commit()
        child = self._start(run_inputs={})
        self.assertEqual(child.run_inputs, {"note": "x"})

        self.child_wf.static_attributes = [
            {"name": "note", "type": "string", "default": None, "required": True}
        ]
        self.db.commit()
        with self.assertRaises(ValidationFailedError):
            self._start(run_inputs={})

    def test_parent_without_a_triggering_user_is_refused(self) -> None:
        parent = self._run(self.parent_wf, triggered_by_id=None)
        with self.assertRaises(ValidationFailedError):
            self._start(parent=parent)

    def test_acting_user_needs_execute_permission(self) -> None:
        self.allowed = False
        with self.assertRaises(AccessDeniedError):
            self._start()
        self.assertEqual(self.db.query(WorkflowRun).count(), 1)

    def test_private_workflow_of_someone_else_is_refused(self) -> None:
        private = self._workflow("secret", creator_id=OTHER, visibility="private")
        with self.assertRaises(AccessDeniedError):
            self._start(workflow=private)

    def test_unknown_workflow_is_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.start_child_run(self.parent, 9999, run_inputs={})

    def test_a_workflow_cannot_start_itself(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self._start(workflow=self.parent_wf)

    def test_a_workflow_cannot_start_an_ancestor(self) -> None:
        grandchild_wf = self._workflow("grandchild")
        child = self._start()
        with self.assertRaises(ValidationFailedError):
            self._start(parent=child, workflow=self.parent_wf)
        # a different workflow is fine
        self.assertEqual(self._start(parent=child, workflow=grandchild_wf).parent_run_id, child.id)

    def test_chain_depth_is_limited(self) -> None:
        parent = self.parent
        for i in range(MAX_CHILD_RUN_DEPTH):
            parent = self._start(parent=parent, workflow=self._workflow(f"level-{i}"))
        with self.assertRaises(ValidationFailedError):
            self._start(parent=parent, workflow=self._workflow("one-too-deep"))

    def test_cancelling_the_parent_cancels_active_children_only(self) -> None:
        active = self._run(self.child_wf, parent_run_id=self.parent.id, status="running")
        done = self._run(self.child_wf, parent_run_id=self.parent.id, status="success")
        other = self._run(self.child_wf, status="running")

        self.service.cancel_run(self.parent.id, OWNER)

        for run in (active, done, other, self.parent):
            self.db.refresh(run)
        self.assertEqual(self.parent.status, "cancelled")
        self.assertEqual(active.status, "cancelled")
        self.assertEqual(done.status, "success")
        self.assertEqual(other.status, "running")

    def test_cancelling_reaches_runs_below_a_child_that_already_finished(self) -> None:
        """A wait-off or timed-out child can be done while its own children still run."""
        finished = self._run(self.child_wf, parent_run_id=self.parent.id, status="success")
        grandchild_wf = self._workflow("grandchild")
        grandchild = self._run(grandchild_wf, parent_run_id=finished.id, status="running")
        deeper = self._run(grandchild_wf, parent_run_id=grandchild.id, status="pending")

        self.service.cancel_run(self.parent.id, OWNER)

        for run in (finished, grandchild, deeper):
            self.db.refresh(run)
        self.assertEqual(finished.status, "success")
        self.assertEqual(grandchild.status, "cancelled")
        self.assertEqual(deeper.status, "cancelled")

    def test_a_cycle_in_the_links_cannot_loop_the_cancel(self) -> None:
        a = self._run(self.child_wf, parent_run_id=self.parent.id, status="running")
        b = self._run(self.child_wf, parent_run_id=a.id, status="running")
        a.parent_run_id = b.id  # corrupt data: a <-> b
        self.db.commit()
        self.service.cancel_child_runs(a.id)
        self.db.refresh(b)
        self.assertEqual(b.status, "cancelled")

    def test_a_run_that_is_no_longer_active_cannot_start_children(self) -> None:
        for status in ("cancelled", "failed", "success"):
            with self.subTest(status=status):
                parent = self._run(self.parent_wf, status=status)
                before = self.db.query(WorkflowRun).count()
                with self.assertRaises(ValidationFailedError):
                    self._start(parent=parent)
                self.assertEqual(self.db.query(WorkflowRun).count(), before)

    def test_a_child_that_lands_while_the_parent_is_being_cancelled_is_cancelled(self) -> None:
        """Operator cancel marks the parent and sweeps once; a start that slipped in between
        must not leave a running run behind."""
        original = RunService._create_and_dispatch_run

        def racing(service, *args, **kwargs):
            run = original(service, *args, **kwargs)
            self.parent.status = "cancelled"  # the cancel lands right after the child exists
            self.db.commit()
            return run

        with patch.object(RunService, "_create_and_dispatch_run", racing):
            with self.assertRaises(ValidationFailedError):
                self._start()

        child = self.db.query(WorkflowRun).order_by(WorkflowRun.id.desc()).first()
        self.assertNotEqual(child.id, self.parent.id)
        self.assertEqual(child.status, "cancelled")

    def _delete_ancestors(self, *runs: WorkflowRun, orphan: WorkflowRun) -> None:
        """What ON DELETE SET NULL does when finished runs are deleted or purged."""
        for run in runs:
            self.db.delete(run)
        orphan.parent_run_id = None
        self.db.commit()

    def test_the_recursion_guard_survives_deleted_ancestors(self) -> None:
        child = self._start()
        grandchild = self._start(parent=child, workflow=self._workflow("grandchild"))
        self._delete_ancestors(self.parent, child, orphan=grandchild)

        with self.assertRaises(ValidationFailedError):
            self._start(parent=grandchild, workflow=self.parent_wf)
        with self.assertRaises(ValidationFailedError):
            self._start(parent=grandchild, workflow=self.child_wf)

    def test_the_depth_limit_survives_deleted_ancestors(self) -> None:
        runs = [self.parent]
        for i in range(MAX_CHILD_RUN_DEPTH):
            runs.append(self._start(parent=runs[-1], workflow=self._workflow(f"level-{i}")))
        self._delete_ancestors(*runs[:-1], orphan=runs[-1])

        with self.assertRaises(ValidationFailedError):
            self._start(parent=runs[-1], workflow=self._workflow("one-too-deep"))

    def test_child_snapshot_reports_status_and_worst_step(self) -> None:
        child = self._run(self.child_wf, parent_run_id=self.parent.id, status="success")
        self.db.add_all(
            [
                WorkflowStepResult(
                    run_id=child.id, step_node_id=n, step_type="x", step_name=n, status=s
                )
                for n, s in (("a", "success"), ("b", "partial"))
            ]
        )
        self.db.commit()
        snapshot = self.service.child_run_snapshot(child.id)
        self.assertEqual(snapshot.status, "success")
        self.assertEqual(snapshot.worst_step_status, "partial")
        self.assertTrue(snapshot.is_terminal)

    def test_snapshot_of_missing_run_is_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.child_run_snapshot(424242)


if __name__ == "__main__":
    unittest.main()
