"""open-change-request executor — stage a rendered config change as a ChangeRequest.

Git and Redis are faked; the DB is in-memory SQLite. See doc/CICD_PIPELINE.md.
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.models.background_tier import WorkflowBackgroundTier
from core.models.change_requests import ChangeRequest
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.workflow_context import DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.open_change_request.executor import execute

NODE_ID = "n-cr"


def _fake_git_service(repo_root: Path) -> MagicMock:
    svc = MagicMock()
    svc.open_or_clone.return_value = MagicMock(name="repo")
    svc.get_repo_path.return_value = repo_root
    svc.commit.return_value = SimpleNamespace(
        success=True, commit_sha="deadbeef00", files_changed=1, message="Committed 1 files"
    )
    svc.push.return_value = SimpleNamespace(
        success=True, pushed=True, branch="manus/cr-42", message="pushed"
    )
    svc.diff_refs.return_value = "diff --git a/d1.cfg b/d1.cfg\n+hostname d1\n"
    return svc


class OpenChangeRequestExecutorTests(unittest.IsolatedAsyncioTestCase):
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
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name)

        self.artifacts = InMemoryArtifactService()
        self.git = _fake_git_service(self.repo_root)

        patches = [
            patch(
                "workflow_steps.open_change_request.executor.load_git_repository",
                return_value={"id": 3, "name": "r", "url": "x", "branch": "main"},
            ),
            patch("service_factory.build_git_service", return_value=self.git),
            patch(
                "workflow_steps.open_change_request.executor.repo_stage_lock",
                lambda *_a, **_k: contextlib.nullcontext(),
            ),
            patch(
                "workflow_steps.open_change_request.executor.get_db_session",
                side_effect=lambda: self.Session(),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def _context_with_running_config(self) -> WorkflowContext:
        ref = await self.artifacts.store(
            content="hostname d1\n", kind="running_config", device_id="d1", run_id="run-uuid"
        )
        device = DeviceContext(
            id="d1", name="d1", hostname="d1.local", running_config_ref=ref
        )
        return WorkflowContext(run_id="run-uuid", workflow_id="7", devices={"d1": device})

    async def _context_with_rendered_template(
        self, *, node_id: str = "render-1"
    ) -> WorkflowContext:
        ref = await self.artifacts.store(
            content="hostname d1\n", kind="rendered_template", device_id="d1", run_id="run-uuid"
        )
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1.local",
            parsed={
                "device_config": {
                    "artifact_ref": ref.model_dump(mode="json"),
                    "kind": "rendered_template",
                    "step_node_id": node_id,
                    "output_key": "device_config",
                }
            },
        )
        return WorkflowContext(run_id="run-uuid", workflow_id="7", devices={"d1": device})

    def _run(self) -> SimpleNamespace:
        return SimpleNamespace(id=42, device_ids=["d1"], run_inputs={"vlan": 10})

    async def test_stages_change_request(self) -> None:
        context = await self._context_with_running_config()
        config = {
            "git_repository_id": 3,
            "content_source": "running_config",
            "filename_template": "{device.name}.cfg",
            "branch_template": "manus/cr-{run.id}",
            "deploy_workflow_id": 9,
        }

        with self.assertLogs(
            "workflow_steps.open_change_request.executor", level="INFO"
        ) as logs:
            outcomes = await execute(
                config=config,
                context=context,
                run=self._run(),
                artifact_service=self.artifacts,
                node_id=NODE_ID,
                device_sessions=None,
            )

        self.assertEqual([o.name for o in outcomes], ["success"])
        self.git.checkout_new_branch.assert_called_once()
        _repo, branch_arg, base_arg = self.git.checkout_new_branch.call_args.args
        self.assertEqual(branch_arg, "manus/cr-42")
        self.assertEqual(base_arg, "main")
        self.assertTrue(self.git.push.call_args.kwargs["force"])
        self.assertEqual(self.git.push.call_args.kwargs["branch"], "manus/cr-42")
        self.assertTrue((self.repo_root / "d1.cfg").exists())

        meta = outcomes[0].context.metadata[f"{NODE_ID}.change_request"]
        self.assertTrue(meta["success"])
        self.assertEqual(meta["branch"], "manus/cr-42")
        self.assertEqual(meta["commit_sha"], "deadbeef00")
        self.assertEqual(meta["diff_stats"]["additions"], 1)

        row = self.db.execute(select(ChangeRequest)).scalar_one()
        self.assertEqual(row.status, "staged")
        self.assertEqual(row.device_ids, ["d1"])
        self.assertEqual(row.run_inputs, {"vlan": 10})
        self.assertEqual(row.deploy_workflow_id, 9)
        self.assertEqual(row.commit_sha, "deadbeef00")
        self.assertIsNotNone(row.diff_artifact_id)

        joined = "\n".join(logs.output)
        self.assertIn("open-change-request started", joined)
        self.assertIn("created change_request_id=", joined)

    async def test_rendered_template_without_source_step_node_id(self) -> None:
        # source_step_node_id is optional for open-change-request: with it unset,
        # every rendered template on the devices is committed.
        context = await self._context_with_rendered_template()
        outcomes = await execute(
            config={"git_repository_id": 3, "content_source": "rendered_template"},
            context=context,
            run=self._run(),
            artifact_service=self.artifacts,
            node_id=NODE_ID,
            device_sessions=None,
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertTrue((self.repo_root / "d1.cfg").exists())
        self.assertEqual(self.db.execute(select(ChangeRequest)).scalar_one().status, "staged")

    async def test_missing_git_repository_id_fails(self) -> None:
        context = await self._context_with_running_config()
        outcomes = await execute(
            config={"content_source": "running_config"},
            context=context,
            run=self._run(),
            artifact_service=self.artifacts,
            node_id=NODE_ID,
            device_sessions=None,
        )
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(self.db.execute(select(ChangeRequest)).all(), [])

    async def test_push_failure_returns_failure_outcome(self) -> None:
        context = await self._context_with_running_config()
        self.git.push.return_value = SimpleNamespace(
            success=False, pushed=False, branch="manus/cr-42", message="rejected"
        )
        outcomes = await execute(
            config={"git_repository_id": 3, "content_source": "running_config"},
            context=context,
            run=self._run(),
            artifact_service=self.artifacts,
            node_id=NODE_ID,
            device_sessions=None,
        )
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(self.db.execute(select(ChangeRequest)).all(), [])


if __name__ == "__main__":
    unittest.main()
