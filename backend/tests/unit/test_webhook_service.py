"""GitWebhookService — inbound webhook → change-request advancement.

Git dispatch, Redis, and the rate limiter are faked; DB is in-memory SQLite.
See doc/CICD_PIPELINE.md §3.5.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.background_tier import WorkflowBackgroundTier
from core.models.change_requests import ChangeRequest
from core.models.git import GitRepository
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from services.change_requests.change_request_service import ChangeRequestService
from services.change_requests.webhook_service import GitWebhookService
from services.git.repository_service import GitRepositoryService

SECRET = "hook-secret"
COMMIT = "deadbeefcafe"


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, key):  # noqa: ANN001
        return self.store.get(key)

    def set(self, key, data, ttl_seconds):  # noqa: ANN001
        self.store[key] = data


class _FakeLimiter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def check(self, key: str) -> None:
        self.calls.append(key)


def _github_headers(body: bytes, *, delivery: str = "d-1") -> dict[str, str]:
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": sig, "X-GitHub-Delivery": delivery}


class GitWebhookServiceTests(unittest.TestCase):
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
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        self.db.add(User(id=1, username="admin", password_hash="x"))
        self.deploy_wf = Workflow(
            uuid="wf-d", name="Deploy", creator_id=1, visibility="public",
            canvas_nodes=[], canvas_edges=[],
        )
        self.db.add(self.deploy_wf)
        self.db.commit()

        self.repo_id = GitRepositoryService(self.db).create_repository(
            {
                "name": "configs",
                "category": "device_configs",
                "url": "https://example.com/x.git",
                "webhook_secret": SECRET,
            }
        )

        self.cache = _FakeCache()
        self.limiter = _FakeLimiter()
        fake_ref = MagicMock(workflow_run_id="h-1")
        for target, value in [
            ("service_factory.build_cache_service", self.cache),
            ("service_factory.build_login_rate_limiter", self.limiter),
        ]:
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch(
            "hatchet.workflows.workflow_run.workflow.run_no_wait", return_value=fake_ref
        )
        self.mock_run_no_wait = p.start()
        self.addCleanup(p.stop)

    def _staged_cr(self, *, commit: str = COMMIT) -> ChangeRequest:
        return ChangeRequestService(self.db).create_from_step(
            source_workflow_id=None,
            source_run_id=None,
            deploy_workflow_id=self.deploy_wf.id,
            git_repository_id=self.repo_id,
            base_branch="main",
            branch="manus/cr-1",
            commit_sha=commit,
            title="t",
            device_ids=["d1"],
            run_inputs={},
            diff_artifact_id="a1",
            diff_stats={},
            expires_after_hours=168,
        )

    def _set_auto_deploy(self, value: bool) -> None:
        GitRepositoryService(self.db).update_repository(
            self.repo_id, {"webhook_auto_deploy": value}
        )

    def _github_push_body(self, *, commit: str = COMMIT) -> bytes:
        return json.dumps(
            {"ref": "refs/heads/manus/cr-1", "after": commit, "commits": [{"id": commit}]}
        ).encode()

    def _process(self, body: bytes, headers: dict[str, str]):  # noqa: ANN201
        return GitWebhookService(self.db).process(
            git_repository_id=self.repo_id,
            raw_body=body,
            headers=headers,
            client_host="10.0.0.9",
        )

    def test_valid_webhook_marks_reviewed_when_not_auto_deploy(self) -> None:
        cr = self._staged_cr()
        body = self._github_push_body()

        status, payload = self._process(body, _github_headers(body))

        self.assertEqual(status, 202)
        self.assertEqual(payload, {"status": "reviewed", "change_request_id": cr.id})
        self.db.refresh(cr)
        self.assertEqual(cr.status, "approved")
        self.mock_run_no_wait.assert_not_called()

    def test_valid_webhook_auto_deploys(self) -> None:
        cr = self._staged_cr()
        self._set_auto_deploy(True)
        body = self._github_push_body()

        status, payload = self._process(body, _github_headers(body))

        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "approved")
        self.db.refresh(cr)
        self.assertEqual(cr.status, "deploying")
        self.mock_run_no_wait.assert_called_once()

    def test_bad_signature_rejected(self) -> None:
        self._staged_cr()
        body = self._github_push_body()
        headers = _github_headers(body)
        headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64

        status, payload = self._process(body, headers)
        self.assertEqual(status, 401)
        self.assertEqual(payload, {"detail": "invalid signature"})

    def test_missing_signature_rejected(self) -> None:
        body = self._github_push_body()
        status, payload = self._process(body, {"X-GitHub-Delivery": "d-x"})
        self.assertEqual(status, 401)
        self.assertEqual(payload, {"detail": "missing signature"})

    def test_missing_secret_fails_closed(self) -> None:
        GitRepositoryService(self.db).update_repository(
            self.repo_id, {"webhook_secret": ""}
        )
        body = self._github_push_body()
        status, payload = self._process(body, _github_headers(body))
        self.assertEqual(status, 401)
        self.assertEqual(payload, {"detail": "webhook not configured"})

    def test_no_matching_change_request_is_ignored(self) -> None:
        self._staged_cr(commit="other-sha")
        body = self._github_push_body(commit=COMMIT)
        status, payload = self._process(body, _github_headers(body))
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ignored"})

    def test_replayed_delivery_is_deduped(self) -> None:
        self._staged_cr()
        body = self._github_push_body()
        headers = _github_headers(body, delivery="dup-1")

        first_status, _ = self._process(body, headers)
        self.assertEqual(first_status, 202)

        second_status, payload = self._process(body, headers)
        self.assertEqual(second_status, 200)
        self.assertEqual(payload, {"status": "duplicate"})

    def test_gitlab_push_with_checkout_sha_matches(self) -> None:
        cr = self._staged_cr()
        body = json.dumps(
            {"object_kind": "push", "ref": "refs/heads/manus/cr-1", "checkout_sha": COMMIT}
        ).encode()
        headers = {"X-Gitlab-Token": SECRET, "X-Gitlab-Event-UUID": "g-1"}

        status, payload = self._process(body, headers)
        self.assertEqual(status, 202)
        self.assertEqual(payload["change_request_id"], cr.id)

    def test_already_actioned_change_request_is_ignored(self) -> None:
        cr = self._staged_cr()
        ChangeRequestService(self.db).reject(cr.id, actor_user_id=1, reason="x")
        body = self._github_push_body()

        status, payload = self._process(body, _github_headers(body, delivery="d-2"))
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ignored"})


if __name__ == "__main__":
    unittest.main()
