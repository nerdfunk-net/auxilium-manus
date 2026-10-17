"""from-change-request executor — inventory step for a deploy workflow.

Rebuilds DeviceContexts from the change request's device snapshot, checks out
the CR branch (git faked), and loads each device's committed config.
See doc/CICD_PIPELINE.md §3.3.
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
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
from models.workflow_context import Capability, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.change_requests.change_request_service import ChangeRequestService
from workflow_steps.from_change_request.executor import execute

NODE_ID = "n-fcr"


class FromChangeRequestExecutorTests(unittest.IsolatedAsyncioTestCase):
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
                GitRepository.__table__,
                ChangeRequest.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name)
        (self.repo_root / "d1.cfg").write_text("hostname d1\n", encoding="utf-8")

        self.git = MagicMock()
        self.repo = MagicMock(name="repo")
        self.repo.head.commit.hexsha = "c0ffee"
        self.git.open_or_clone.return_value = self.repo
        self.git.fetch.return_value = SimpleNamespace(success=True, message="ok")
        self.git.get_repo_path.return_value = self.repo_root

        self.artifacts = InMemoryArtifactService()

        for target, value in [
            ("service_factory.build_git_service", self.git),
            ("workflow_steps.from_change_request.executor.git_repo_lock", None),
            (
                "workflow_steps.from_change_request.executor.load_git_repository",
                {"id": 3, "name": "r", "url": "x", "branch": "main"},
            ),
            ("core.database.get_db_session", None),
        ]:
            if target.endswith("git_repo_lock"):
                p = patch(target, lambda *_a, **_k: contextlib.nullcontext(MagicMock(name="lease")))
                p.start()
                self.addCleanup(p.stop)
                continue
            p = patch(
                target,
                **(
                    {"side_effect": lambda: self.Session()}
                    if target.endswith("get_db_session")
                    else {"return_value": value}
                ),
            )
            p.start()
            self.addCleanup(p.stop)

    def _cr_with_devices(self, devices: list[dict]) -> ChangeRequest:
        return ChangeRequestService(self.db).create_from_step(
            source_workflow_id=None,
            source_run_id=None,
            deploy_workflow_id=None,
            git_repository_id=3,
            base_branch="main",
            branch="manus/cr-7",
            commit_sha="c0ffee",
            title="t",
            device_ids=[d["id"] for d in devices],
            devices=devices,
            run_inputs={},
            diff_artifact_id=None,
            diff_stats=None,
            expires_after_hours=0,
        )

    def _ctx(self) -> WorkflowContext:
        return WorkflowContext(run_id="run-uuid", workflow_id="1", devices={})

    async def test_requires_a_change_request_run(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=self._ctx(),
                run=SimpleNamespace(id=1, change_request_id=None),
                artifact_service=self.artifacts,
                node_id=NODE_ID,
                device_sessions=None,
            )

    async def test_rebuilds_devices_checks_out_branch_and_loads_configs(self) -> None:
        cr = self._cr_with_devices(
            [
                {
                    "id": "d1",
                    "name": "d1",
                    "hostname": "d1.lab",
                    "platform": "cisco_ios",
                    "network_driver": "cisco_ios",
                    "primary_ip4": "192.0.2.1",
                    "config_path": "d1.cfg",
                }
            ]
        )

        outcomes = await execute(
            config={"checkout_branch": True, "load_configs": True},
            context=self._ctx(),
            run=SimpleNamespace(id=99, change_request_id=cr.id),
            artifact_service=self.artifacts,
            node_id=NODE_ID,
            device_sessions=None,
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        devices = outcomes[0].context.devices
        self.assertIn("d1", devices)
        d1 = devices["d1"]
        self.assertEqual(d1.hostname, "d1.lab")
        self.assertEqual(d1.platform, "cisco_ios")
        self.assertIn(Capability.IDENTITY, d1.capabilities)
        self.assertIn(Capability.RUNNING_CONFIG, d1.capabilities)
        self.assertIsNotNone(d1.running_config_ref)

        _repo, branch, base = self.git.checkout_new_branch.call_args.args
        self.assertEqual(branch, "manus/cr-7")
        self.assertEqual(base, "origin/manus/cr-7")

        meta = outcomes[0].context.metadata[f"{NODE_ID}.change_request"]
        self.assertEqual(meta["change_request_id"], cr.id)
        self.assertEqual(meta["branch"], "manus/cr-7")

    async def _assert_refused(self, bad: str) -> None:
        from core.domain_exceptions import AccessDeniedError

        cr = self._cr_with_devices(
            [{"id": "d1", "name": "d1", "hostname": "d1.lab", "config_path": bad}]
        )
        with self.assertRaises(AccessDeniedError):
            await execute(
                config={"checkout_branch": True, "load_configs": True},
                context=self._ctx(),
                run=SimpleNamespace(id=99, change_request_id=cr.id),
                artifact_service=self.artifacts,
                node_id=NODE_ID,
                device_sessions=None,
            )

    async def test_config_path_with_dotdot_is_refused(self) -> None:
        await self._assert_refused("../../etc/passwd")

    async def test_absolute_config_path_is_refused(self) -> None:
        await self._assert_refused("/etc/passwd")

    async def test_deploy_refuses_when_branch_moved_after_review(self) -> None:
        from services.git.failure import GitOperationError

        cr = self._cr_with_devices(
            [{"id": "d1", "name": "d1", "hostname": "d1.lab", "config_path": "d1.cfg"}]
        )
        self.repo.head.commit.hexsha = "badbadbadbad"  # commit B pushed after review of c0ffee
        with self.assertRaises(GitOperationError) as ctx:
            await execute(
                config={"checkout_branch": True, "load_configs": True},
                context=self._ctx(),
                run=SimpleNamespace(id=99, change_request_id=cr.id),
                artifact_service=self.artifacts,
                node_id=NODE_ID,
                device_sessions=None,
            )
        self.assertEqual(ctx.exception.failure.kind, "ref_mismatch")
        # the configured branch is restored even though the block raised
        self.git.ensure_branch.assert_called()

    async def test_deploy_refuses_a_change_request_without_a_reviewed_commit(self) -> None:
        from services.git.failure import GitOperationError

        cr = self._cr_with_devices(
            [{"id": "d1", "name": "d1", "hostname": "d1.lab", "config_path": "d1.cfg"}]
        )
        cr.commit_sha = None
        self.db.commit()
        with self.assertRaises(GitOperationError) as ctx:
            await execute(
                config={"checkout_branch": True, "load_configs": True},
                context=self._ctx(),
                run=SimpleNamespace(id=99, change_request_id=cr.id),
                artifact_service=self.artifacts,
                node_id=NODE_ID,
                device_sessions=None,
            )
        self.assertEqual(ctx.exception.failure.kind, "ref_mismatch")
        self.git.ensure_branch.assert_called()

    async def test_branch_is_restored_after_deploy(self) -> None:
        cr = self._cr_with_devices(
            [{"id": "d1", "name": "d1", "hostname": "d1.lab", "config_path": "d1.cfg"}]
        )
        await execute(
            config={"checkout_branch": True, "load_configs": True},
            context=self._ctx(),
            run=SimpleNamespace(id=99, change_request_id=cr.id),
            artifact_service=self.artifacts,
            node_id=NODE_ID,
            device_sessions=None,
        )
        self.git.ensure_branch.assert_called_once()
        self.assertEqual(self.git.ensure_branch.call_args.args[1], "main")

    async def test_empty_device_snapshot_raises(self) -> None:
        cr = self._cr_with_devices([])
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=self._ctx(),
                run=SimpleNamespace(id=1, change_request_id=cr.id),
                artifact_service=self.artifacts,
                node_id=NODE_ID,
                device_sessions=None,
            )


if __name__ == "__main__":
    unittest.main()
