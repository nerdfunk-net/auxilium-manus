"""Phase 4 of the CI/CD pipeline: deploy runs read the change-request branch,
and a finished deploy run flips its change request to deployed/failed.

See doc/CICD_PIPELINE.md.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.background_tier import WorkflowBackgroundTier
from core.models.change_requests import ChangeRequest
from core.models.git import GitRepository
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.workflow_context import WorkflowContext
from repositories.run_repository import RunRepository
from services.change_requests.change_request_service import (
    ChangeRequestService,
    maybe_reconcile_deploy_run,
)
from workflow_steps.common.change_request_context import resolve_cr_ref
from workflow_steps.common.git_workflow_step import run_git_workflow_step


def _make_db():  # noqa: ANN202
    engine = create_engine("sqlite:///:memory:")
    Workflow.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Workflow.__table__,
            WorkflowRun.__table__,
            WorkflowStepResult.__table__,
            WorkflowBackgroundTier.__table__,
            GitRepository.__table__,
            ChangeRequest.__table__,
        ],
    )
    return engine, sessionmaker(bind=engine)


class ResolveCrRefTests(unittest.TestCase):
    def test_returns_none_without_change_request_id(self) -> None:
        self.assertIsNone(resolve_cr_ref(SimpleNamespace(change_request_id=None)))

    def test_returns_branch_for_deploy_run(self) -> None:
        engine, Session = _make_db()
        self.addCleanup(engine.dispose)
        db = Session()
        self.addCleanup(db.close)
        cr = ChangeRequestService(db).create_from_step(
            source_workflow_id=None, source_run_id=None, deploy_workflow_id=None,
            git_repository_id=1, base_branch="main", branch="manus/cr-5",
            commit_sha="c0ffee", title="t", device_ids=[], run_inputs={},
            diff_artifact_id=None, diff_stats=None, expires_after_hours=0,
        )
        with patch("core.database.get_db_session", side_effect=lambda: Session()):
            ref = resolve_cr_ref(SimpleNamespace(change_request_id=cr.id))
        self.assertEqual(ref, ("manus/cr-5", "c0ffee"))


class GitWorkflowStepBranchOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, config, run):  # noqa: ANN202
        seen: dict = {}

        def _operation(_git, repository, _config, _context):  # noqa: ANN001
            seen["branch"] = repository["branch"]
            return {"success": True, "operation": "pull", "branch": repository["branch"]}

        with (
            patch(
                "workflow_steps.common.git_workflow_step.load_git_repository",
                return_value={"id": 1, "name": "r", "url": "x", "branch": "main"},
            ),
            patch("service_factory.build_git_service", return_value=MagicMock()),
        ):
            await run_git_workflow_step(
                config=config,
                context=WorkflowContext(run_id="u", workflow_id="1", devices={}),
                run=run,
                artifact_service=MagicMock(),
                node_id="n",
                step_id="git-pull",
                operation=_operation,
                operation_name="pull",
            )
        return seen

    async def test_default_branch_used_without_opt_in(self) -> None:
        seen = await self._run(
            config={"git_repository_id": 1},
            run=SimpleNamespace(change_request_id=7),
        )
        self.assertEqual(seen["branch"], "main")

    async def test_change_request_branch_used_when_opted_in(self) -> None:
        with patch(
            "workflow_steps.common.change_request_context.resolve_cr_ref",
            return_value=("manus/cr-9", "sha9"),
        ):
            seen = await self._run(
                config={"git_repository_id": 1, "use_change_request_branch": True},
                run=SimpleNamespace(change_request_id=9),
            )
        self.assertEqual(seen["branch"], "manus/cr-9")

    async def test_opt_in_without_deploy_run_keeps_default(self) -> None:
        seen = await self._run(
            config={"git_repository_id": 1, "use_change_request_branch": True},
            run=SimpleNamespace(change_request_id=None),
        )
        self.assertEqual(seen["branch"], "main")


class MaybeReconcileDeployRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.Session = _make_db()
        self.addCleanup(self.engine.dispose)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.db.add(User(id=1, username="a", password_hash="x"))
        self.db.commit()

    def test_no_op_for_non_deploy_run(self) -> None:
        run = RunRepository(self.db).create_run(
            workflow_id=1, triggered_by_id=1, trigger_type="manual", device_ids=[]
        )
        maybe_reconcile_deploy_run(self.db, run)  # must not raise

    def test_flips_change_request_when_deploy_run_succeeds(self) -> None:
        cr = ChangeRequestService(self.db).create_from_step(
            source_workflow_id=None, source_run_id=None, deploy_workflow_id=None,
            git_repository_id=1, base_branch="main", branch="manus/cr-1",
            commit_sha="c1", title="t", device_ids=[], run_inputs={},
            diff_artifact_id=None, diff_stats=None, expires_after_hours=0,
        )
        run = RunRepository(self.db).create_run(
            workflow_id=1, triggered_by_id=1, trigger_type="webhook", device_ids=[]
        )
        # Simulate approve() having stamped these.
        ChangeRequestService(self.db).repo.transition(
            cr, expected_statuses={"staged"}, new_status="deploying", deploy_run_id=run.id
        )
        RunRepository(self.db).update_run_status(run, status="success")
        run.change_request_id = cr.id
        self.db.commit()

        maybe_reconcile_deploy_run(self.db, run)
        self.assertEqual(
            ChangeRequestService(self.db).repo.get_by_id(cr.id).status, "deployed"
        )


if __name__ == "__main__":
    unittest.main()
