"""Tests for RetentionService: purges old runs and their orphaned artifacts."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from services.artifacts import FilesystemArtifactService
from services.execution.retention_service import RetentionService

USER_ID = 1


class RetentionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        user = User(username="tester", password_hash="hash", is_active=True)
        user.id = USER_ID
        self.db.add(user)
        self.db.commit()

        workflow = Workflow(name="wf-1", creator_id=USER_ID, visibility="public")
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        self.workflow = workflow

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.artifact_service = FilesystemArtifactService(Path(self._tmp.name))

    def _make_run(self, *, uuid: str, status: str, created_at: datetime) -> WorkflowRun:
        run = WorkflowRun(
            uuid=uuid,
            workflow_id=self.workflow.id,
            status=status,
            trigger_type="manual",
            run_mode="normal",
            device_ids=[],
            created_at=created_at,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    async def test_purge_deletes_old_runs_and_their_orphaned_artifacts(self) -> None:
        now = datetime.now(UTC)
        old_run = self._make_run(
            uuid="old-run", status="success", created_at=now - timedelta(days=100)
        )
        recent_run = self._make_run(
            uuid="recent-run", status="success", created_at=now - timedelta(days=1)
        )

        old_ref = await self.artifact_service.store(
            content="stale config", kind="running_config", device_id="d1", run_id=old_run.uuid
        )
        recent_ref = await self.artifact_service.store(
            content="fresh config", kind="running_config", device_id="d1", run_id=recent_run.uuid
        )

        service = RetentionService(self.db, artifact_service=self.artifact_service)
        result = service.purge_workflow_runs(retention_days=90, batch_size=500)

        self.assertEqual(result.runs_deleted, 1)
        self.assertEqual(result.artifacts_deleted, 1)
        self.assertIsNone(self.artifact_service.read_meta(old_ref.artifact_id))
        self.assertIsNotNone(self.artifact_service.read_meta(recent_ref.artifact_id))

    async def test_dry_run_does_not_delete_anything(self) -> None:
        now = datetime.now(UTC)
        old_run = self._make_run(
            uuid="old-run", status="success", created_at=now - timedelta(days=100)
        )
        old_ref = await self.artifact_service.store(
            content="stale config", kind="running_config", device_id="d1", run_id=old_run.uuid
        )

        service = RetentionService(self.db, artifact_service=self.artifact_service)
        result = service.purge_workflow_runs(retention_days=90, batch_size=500, dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertEqual(result.runs_deleted, 1)
        self.assertEqual(result.artifacts_deleted, 0)
        self.assertIsNotNone(self.artifact_service.read_meta(old_ref.artifact_id))


if __name__ == "__main__":
    unittest.main()
