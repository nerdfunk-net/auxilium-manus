"""Tests for RetentionService: purges old runs and their orphaned artifacts."""

from __future__ import annotations

import os
import tempfile
import time
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
            device_ids=[],
            created_at=created_at,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _age_artifact(self, artifact_id: str, seconds: float = 7200) -> None:
        old = time.time() - seconds
        meta = Path(self._tmp.name) / "artifacts" / f"{artifact_id}.meta.json"
        os.utime(meta, (old, old))

    async def test_sweep_uses_grace_period(self) -> None:
        # An artifact of a run the sweep's snapshot does not know, but written moments ago.
        young_ref = await self.artifact_service.store(
            content="x", kind="running_config", device_id="d1", run_id="created-after-snapshot"
        )
        service = RetentionService(self.db, artifact_service=self.artifact_service)
        result = service.purge_workflow_runs(retention_days=90, batch_size=500)
        self.assertEqual(result.artifacts_deleted, 0)
        self.assertIsNotNone(self.artifact_service.read_meta(young_ref.artifact_id))

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

        self._age_artifact(old_ref.artifact_id)

        service = RetentionService(self.db, artifact_service=self.artifact_service)
        result = service.purge_workflow_runs(retention_days=90, batch_size=500)

        self.assertEqual(result.runs_deleted, 1)
        self.assertEqual(result.artifacts_deleted, 1)
        self.assertIsNone(self.artifact_service.read_meta(old_ref.artifact_id))
        self.assertIsNotNone(self.artifact_service.read_meta(recent_ref.artifact_id))

    async def test_purge_removes_log_attribute_dirs_of_deleted_runs(self) -> None:
        root = Path(self._tmp.name) / "log-attributes"
        now = datetime.now(UTC)
        live = self._make_run(uuid="live-run", status="success", created_at=now)
        for run_uuid in (live.uuid, "gone-old", "gone-young"):
            directory = root / str(self.workflow.id) / run_uuid
            directory.mkdir(parents=True)
            (directory / "out.txt").write_text("x")
        old = time.time() - 7200
        os.utime(root / str(self.workflow.id) / "gone-old", (old, old))

        service = RetentionService(
            self.db, artifact_service=self.artifact_service, log_attributes_root=root
        )
        service.purge_workflow_runs(retention_days=90, batch_size=500)

        remaining = sorted(p.name for p in (root / str(self.workflow.id)).iterdir())
        self.assertEqual(remaining, ["gone-young", "live-run"])

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
