"""Tests for services/execution/background_tier_service.py."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock

from core.domain_exceptions import AccessDeniedError, NotFoundError
from services.execution.background_tier_service import BackgroundTierService, _to_response


def _tier_row(**over) -> MagicMock:
    row = MagicMock()
    row.id = over.get("id", 1)
    row.uuid = over.get("uuid", "tier-uuid")
    row.workflow_id = over.get("workflow_id", 10)
    row.hatchet_workflow_name = over.get("hatchet_workflow_name", "wf-bg-10")
    row.concurrency_limit = over.get("concurrency_limit", 5)
    row.published_by_id = over.get("published_by_id", 7)
    row.created_at = over.get("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    row.updated_at = over.get("updated_at", datetime(2026, 1, 2, tzinfo=UTC))
    return row


def _workflow(visibility: str = "public", creator_id: int = 7) -> MagicMock:
    wf = MagicMock()
    wf.visibility = visibility
    wf.creator_id = creator_id
    return wf


def _service() -> BackgroundTierService:
    svc = BackgroundTierService(MagicMock())
    svc.repo = MagicMock()
    svc.wf_repo = MagicMock()
    svc.run_repo = MagicMock()
    return svc


class BackgroundTierServiceTests(unittest.TestCase):
    def test_to_response_maps_row(self) -> None:
        resp = _to_response(_tier_row())
        self.assertEqual(resp.workflow_id, 10)
        self.assertEqual(resp.concurrency_limit, 5)

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

    def test_get_status_returns_none_when_unpublished(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.get_by_workflow_id.return_value = None
        self.assertIsNone(svc.get_status(10, user_id=7))

    def test_get_status_returns_response_when_published(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.get_by_workflow_id.return_value = _tier_row()
        self.assertEqual(svc.get_status(10, user_id=7).workflow_id, 10)

    def test_publish_delegates_to_repo(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.publish.return_value = _tier_row(concurrency_limit=3)
        data = MagicMock(concurrency_limit=3)
        resp = svc.publish(10, data, user_id=7)
        self.assertEqual(resp.concurrency_limit, 3)
        svc.repo.publish.assert_called_once_with(10, concurrency_limit=3, published_by_id=7)

    def test_has_active_runs(self) -> None:
        svc = _service()
        svc.run_repo.list_runs_for_workflow.return_value = [MagicMock()]
        self.assertTrue(svc.has_active_runs(10))
        svc.run_repo.list_runs_for_workflow.return_value = []
        self.assertFalse(svc.has_active_runs(10))

    def test_unpublish_missing_row_raises(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        svc.repo.get_by_workflow_id.return_value = None
        with self.assertRaises(NotFoundError):
            svc.unpublish(10, user_id=7)

    def test_unpublish_calls_repo(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow(), None)
        row = _tier_row()
        svc.repo.get_by_workflow_id.return_value = row
        svc.unpublish(10, user_id=7)
        svc.repo.unpublish.assert_called_once_with(row)

    def test_unpublish_unchecked_noop_when_absent(self) -> None:
        svc = _service()
        svc.repo.get_by_workflow_id.return_value = None
        svc.unpublish_for_workflow_unchecked(10)
        svc.repo.unpublish.assert_not_called()

    def test_unpublish_unchecked_calls_repo_when_present(self) -> None:
        svc = _service()
        row = _tier_row()
        svc.repo.get_by_workflow_id.return_value = row
        svc.unpublish_for_workflow_unchecked(10)
        svc.repo.unpublish.assert_called_once_with(row)


if __name__ == "__main__":
    unittest.main()
