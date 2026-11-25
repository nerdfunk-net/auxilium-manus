"""Phase 4 of the CI/CD pipeline: a finished deploy run flips its change request to
deployed/failed.

See doc/CICD_PIPELINE.md.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.background_tier import WorkflowBackgroundTier
from core.models.change_requests import ChangeRequest
from core.models.git import GitRepository
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from repositories.run_repository import RunRepository
from services.change_requests.change_request_service import (
    ChangeRequestService,
    maybe_reconcile_deploy_run,
)


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
