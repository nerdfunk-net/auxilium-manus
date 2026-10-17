"""ChangeRequestService — the CI/CD pipeline review-gate state machine.

Covers the atomic transitions (staged → approved → deploying → deployed/failed),
the button-vs-webhook race (exactly one deploy run), reconcile, and expire.
See doc/CICD_PIPELINE.md.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import ConflictError
from core.models.background_tier import WorkflowBackgroundTier
from core.models.change_requests import ChangeRequest
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from repositories.run_repository import RunRepository
from services.change_requests.change_request_service import ChangeRequestService

USER_ID = 1


class ChangeRequestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Workflow.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowBackgroundTier.__table__,
                ChangeRequest.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        self.db.add(User(id=USER_ID, username="admin", email="a@b.c", password_hash="x"))
        self.deploy_wf = Workflow(
            uuid="wf-deploy",
            name="Deploy",
            creator_id=USER_ID,
            visibility="public",
            canvas_nodes=[],
            canvas_edges=[],
        )
        self.db.add(self.deploy_wf)
        self.db.commit()

        self.service = ChangeRequestService(self.db)

        fake_ref = MagicMock(workflow_run_id="hatchet-1")
        p = patch(
            "hatchet.workflows.workflow_run.workflow.run_no_wait", return_value=fake_ref
        )
        self.mock_run_no_wait = p.start()
        self.addCleanup(p.stop)

    def _staged_cr(self, *, commit_sha: str = "abc123", pin_deploy: bool = True) -> ChangeRequest:
        return self.service.create_from_step(
            source_workflow_id=None,
            source_run_id=None,
            deploy_workflow_id=self.deploy_wf.id if pin_deploy else None,
            git_repository_id=3,
            base_branch="main",
            branch="manus/cr-1",
            commit_sha=commit_sha,
            title="t",
            device_ids=["d1", "d2"],
            run_inputs={"vlan": 10},
            diff_artifact_id="art-1",
            diff_stats={"additions": 2, "deletions": 0, "files": 1, "truncated": False},
            expires_after_hours=168,
        )

    def test_approve_dispatches_one_deploy_run_and_captures_inputs(self) -> None:
        cr = self._staged_cr()

        resp = self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")

        self.assertEqual(resp.status, "deploying")
        self.assertIsNotNone(resp.deploy_run_id)
        self.mock_run_no_wait.assert_called_once()

        run, _ = RunRepository(self.db).get_run_by_id(resp.deploy_run_id)
        self.assertEqual(run.change_request_id, cr.id)
        self.assertEqual(run.trigger_type, "manual")
        self.assertEqual(run.device_ids, ["d1", "d2"])
        self.assertEqual(run.run_inputs, {"vlan": 10})

    def test_second_approve_conflicts_and_creates_no_second_run(self) -> None:
        cr = self._staged_cr()
        self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")

        with self.assertRaises(ConflictError):
            self.service.approve(cr.id, actor_user_id=USER_ID, via="webhook")

        self.mock_run_no_wait.assert_called_once()

    def test_webhook_review_then_ui_deploy(self) -> None:
        cr = self._staged_cr()

        reviewed = self.service.mark_reviewed(cr.id, via="webhook")
        self.assertEqual(reviewed.status, "approved")
        self.mock_run_no_wait.assert_not_called()

        deployed = self.service.deploy(cr.id, actor_user_id=USER_ID)
        self.assertEqual(deployed.status, "deploying")
        self.mock_run_no_wait.assert_called_once()

    def test_approve_without_deploy_workflow_conflicts(self) -> None:
        cr = self._staged_cr(pin_deploy=False)
        with self.assertRaises(ConflictError):
            self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")
        # The approver cannot choose a workflow at approval time (S2-02).
        with self.assertRaises(TypeError):
            self.service.approve(  # type: ignore[call-arg]
                cr.id, actor_user_id=USER_ID, via="ui", deploy_workflow_id=self.deploy_wf.id
            )

    def test_approver_cannot_run_private_workflow_of_someone_else(self) -> None:
        from core.domain_exceptions import AccessDeniedError

        self.deploy_wf.visibility = "private"
        self.db.commit()
        cr = self._staged_cr()
        with self.assertRaises(AccessDeniedError):
            self.service.approve(cr.id, actor_user_id=USER_ID + 1, via="ui")
        self.mock_run_no_wait.assert_not_called()
        # The signed webhook (no actor) is authenticated by its signature and still works.
        resp = self.service.approve(cr.id, actor_user_id=None, via="webhook")
        self.assertEqual(resp.status, "deploying")

    def test_reject_checks_visibility(self) -> None:
        from core.domain_exceptions import AccessDeniedError

        src = Workflow(uuid="wf-src", name="Src", creator_id=USER_ID, visibility="private",
                       canvas_nodes=[], canvas_edges=[])
        self.db.add(src)
        self.db.commit()
        cr = self._staged_cr()
        cr.source_workflow_id = src.id
        self.db.commit()
        with self.assertRaises(AccessDeniedError):
            self.service.reject(cr.id, actor_user_id=USER_ID + 1, reason="x")

    def test_reject_from_staged(self) -> None:
        cr = self._staged_cr()
        resp = self.service.reject(cr.id, actor_user_id=USER_ID, reason="nope")
        self.assertEqual(resp.status, "rejected")
        self.assertEqual(resp.reject_reason, "nope")
        with self.assertRaises(ConflictError):
            self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")

    def test_reconcile_flips_deploying_on_terminal_run(self) -> None:
        cr = self._staged_cr()
        resp = self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")
        run, _ = RunRepository(self.db).get_run_by_id(resp.deploy_run_id)

        RunRepository(self.db).update_run_status(run, status="success")
        reconciled = self.service.reconcile(self.service.repo.get_by_id(cr.id))
        self.assertEqual(reconciled.status, "deployed")

    def test_reconcile_marks_failed_with_error(self) -> None:
        cr = self._staged_cr()
        resp = self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")
        run, _ = RunRepository(self.db).get_run_by_id(resp.deploy_run_id)

        RunRepository(self.db).update_run_status(
            run, status="failed", error_message="device unreachable"
        )
        reconciled = self.service.reconcile(self.service.repo.get_by_id(cr.id))
        self.assertEqual(reconciled.status, "failed")
        self.assertEqual(reconciled.deploy_error, "device unreachable")

    def test_dispatch_failure_returns_request_to_staged(self) -> None:
        cr = self._staged_cr()
        with patch(
            "services.change_requests.change_request_service.RunService._create_and_dispatch_run",
            side_effect=RuntimeError("engine down"),
        ):
            with self.assertRaises(RuntimeError):
                self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")
        row = self.service.repo.get_by_id(cr.id)
        self.assertEqual(row.status, "staged")
        self.assertIsNone(row.approved_by_id)
        self.assertIn("try again", row.deploy_error)

    def test_dispatch_failure_from_deploy_returns_to_approved(self) -> None:
        cr = self._staged_cr()
        self.service.mark_reviewed(cr.id, via="webhook")
        with patch(
            "services.change_requests.change_request_service.RunService._create_and_dispatch_run",
            side_effect=RuntimeError("engine down"),
        ):
            with self.assertRaises(RuntimeError):
                self.service.deploy(cr.id, actor_user_id=USER_ID)
        self.assertEqual(self.service.repo.get_by_id(cr.id).status, "approved")

    def test_second_click_after_failed_dispatch_succeeds(self) -> None:
        cr = self._staged_cr()
        with patch(
            "services.change_requests.change_request_service.RunService._create_and_dispatch_run",
            side_effect=RuntimeError("engine down"),
        ):
            with self.assertRaises(RuntimeError):
                self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")
        resp = self.service.approve(cr.id, actor_user_id=USER_ID, via="ui")
        self.assertEqual(resp.status, "deploying")

    def _deploying_without_run(self, *, age: timedelta) -> ChangeRequest:
        cr = self._staged_cr()
        self.service.repo.transition(cr, expected_statuses={"staged"}, new_status="deploying")
        cr.updated_at = datetime.now(UTC) - age
        self.db.commit()
        return cr

    def test_reconcile_fails_request_whose_run_was_deleted(self) -> None:
        cr = self._staged_cr()
        self.service.repo.transition(
            cr, expected_statuses={"staged"}, new_status="deploying", deploy_run_id=99999
        )
        reconciled = self.service.reconcile(self.service.repo.get_by_id(cr.id))
        self.assertEqual(reconciled.status, "failed")
        self.assertIn("no longer exists", reconciled.deploy_error)

    def test_reconcile_waits_during_dispatch_grace(self) -> None:
        cr = self._deploying_without_run(age=timedelta(minutes=1))
        reconciled = self.service.reconcile(self.service.repo.get_by_id(cr.id))
        self.assertEqual(reconciled.status, "deploying")

    def test_reconcile_fails_request_without_run_after_grace(self) -> None:
        cr = self._deploying_without_run(age=timedelta(minutes=30))
        reconciled = self.service.reconcile(self.service.repo.get_by_id(cr.id))
        self.assertEqual(reconciled.status, "failed")
        self.assertIn("never created", reconciled.deploy_error)

    def test_expire_sweep(self) -> None:
        cr = self._staged_cr()
        cr.expires_at = datetime.now(UTC) - timedelta(hours=1)
        self.db.commit()

        self.assertEqual(self.service.expire_sweep(), 1)
        self.assertEqual(self.service.repo.get_by_id(cr.id).status, "expired")
        # Idempotent.
        self.assertEqual(self.service.expire_sweep(), 0)

    def test_create_from_step_duplicate_commit_conflicts(self) -> None:
        self._staged_cr(commit_sha="dup")
        with self.assertRaises(ConflictError):
            self._staged_cr(commit_sha="dup")

    def test_get_tolerates_null_json_columns_on_legacy_rows(self) -> None:
        # Rows created before the `devices` column existed have devices=NULL.
        cr = self._staged_cr()
        cr.devices = None
        self.db.commit()
        resp = self.service.get(cr.id, USER_ID)
        self.assertEqual(resp.devices, [])


if __name__ == "__main__":
    unittest.main()
