"""Tests for services/workflow/workflow_ai_session_service.py."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from core.domain_exceptions import AccessDeniedError, NotFoundError
from services.workflow.workflow_ai_session_service import WorkflowAiSessionService


def _session_row(**over) -> MagicMock:
    row = MagicMock()
    row.id = over.get("id", 1)
    row.workflow_id = over.get("workflow_id", 10)
    row.enabled_by_id = over.get("enabled_by_id", 7)
    row.expires_at = over.get("expires_at", datetime(2026, 1, 1, tzinfo=UTC))
    return row


def _workflow(visibility: str = "public", creator_id: int = 7, updated_at=None) -> MagicMock:
    wf = MagicMock()
    wf.visibility = visibility
    wf.creator_id = creator_id
    wf.updated_at = updated_at or datetime(2026, 1, 1, tzinfo=UTC)
    return wf


def _user(user_id: int, username: str) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.username = username
    return user


def _service() -> WorkflowAiSessionService:
    svc = WorkflowAiSessionService(MagicMock())
    svc.repo = MagicMock()
    svc.wf_repo = MagicMock()
    svc.user_repo = MagicMock()
    return svc


class WorkflowAiSessionServiceTests(unittest.TestCase):
    def test_assert_access_missing_workflow_raises(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = None
        with self.assertRaises(NotFoundError):
            svc.get_status(10, user_id=7)

    def test_assert_access_private_other_user_denied(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow("private", creator_id=1), None)
        with self.assertRaises(AccessDeniedError):
            svc.get_status(10, user_id=99)

    def test_assert_access_public_other_user_still_denied(self) -> None:
        # Enabling an AI session grants ai-assistant write access to the
        # workflow via update_workflow_for_ai_session, which trusts this
        # check instead of the normal creator_id check — a workflows:write
        # holder who isn't the owner must not be able to grant that consent
        # just because the workflow happens to be public.
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow("public", creator_id=1), None)
        with self.assertRaises(AccessDeniedError):
            svc.enable(10, user_id=99, ttl_minutes=60)
        svc.repo.create.assert_not_called()

    def test_get_status_inactive_when_no_active_row(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.get_active_for_workflow.return_value = None

        resp = svc.get_status(10, user_id=7)

        self.assertFalse(resp.active)
        self.assertIsNone(resp.expires_at)
        self.assertIsNone(resp.enabled_by_username)

    def test_get_status_active_includes_enabled_by_username(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.get_active_for_workflow.return_value = _session_row(enabled_by_id=7)
        svc.user_repo.get_by_id.return_value = _user(7, "marc")

        resp = svc.get_status(10, user_id=7)

        self.assertTrue(resp.active)
        self.assertEqual(resp.enabled_by_username, "marc")

    def test_enable_computes_expiry_from_ttl(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.create.return_value = _session_row()
        svc.user_repo.get_by_id.return_value = _user(7, "marc")

        svc.enable(10, user_id=7, ttl_minutes=30)

        (workflow_id,), kwargs = svc.repo.create.call_args
        self.assertEqual(workflow_id, 10)
        self.assertEqual(kwargs["enabled_by_id"], 7)
        expected = datetime.now(UTC) + timedelta(minutes=30)
        self.assertLess(abs((kwargs["expires_at"] - expected).total_seconds()), 5)

    def test_disable_delegates_to_repo(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)

        svc.disable(10, user_id=7)

        svc.repo.expire_active_for_workflow.assert_called_once_with(10)

    def test_disable_denies_non_owner_on_private_workflow(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow("private", creator_id=1), None)

        with self.assertRaises(AccessDeniedError):
            svc.disable(10, user_id=99)
        svc.repo.expire_active_for_workflow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
