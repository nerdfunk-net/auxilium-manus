"""Tests for repositories/workflow_ai_session_repository.py — in particular
expire_active_for_workflow, which must expire every currently-active row for
a workflow, not just the newest one (enable() always inserts, never reuses,
so overlapping active rows are a real possibility, not a hypothetical)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.users import User
from core.models.workflow_ai_session import WorkflowAiSession
from core.models.workflows import Workflow
from repositories.workflow_ai_session_repository import WorkflowAiSessionRepository


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.metadata.create_all(
        engine,
        tables=[User.__table__, Workflow.__table__, WorkflowAiSession.__table__],
    )
    return sessionmaker(bind=engine)()


def _future(minutes: int) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


class WorkflowAiSessionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="admin", password_hash="hash", is_active=True)
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)
        self.workflow = Workflow(
            name="test",
            creator_id=self.user.id,
            visibility="private",
            canvas_nodes=[],
            canvas_edges=[],
            canvas_groups=[],
            static_attributes=[],
        )
        self.db.add(self.workflow)
        self.db.commit()
        self.db.refresh(self.workflow)
        self.repo = WorkflowAiSessionRepository(self.db)

    def test_get_active_returns_none_when_all_expired(self) -> None:
        self.repo.create(self.workflow.id, enabled_by_id=self.user.id, expires_at=_future(-5))
        self.assertIsNone(self.repo.get_active_for_workflow(self.workflow.id))

    def test_get_active_returns_row_when_unexpired(self) -> None:
        row = self.repo.create(
            self.workflow.id, enabled_by_id=self.user.id, expires_at=_future(60)
        )
        found = self.repo.get_active_for_workflow(self.workflow.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, row.id)

    def test_expire_active_clears_a_single_row(self) -> None:
        self.repo.create(self.workflow.id, enabled_by_id=self.user.id, expires_at=_future(60))
        self.repo.expire_active_for_workflow(self.workflow.id)
        self.assertIsNone(self.repo.get_active_for_workflow(self.workflow.id))

    def test_expire_active_clears_every_overlapping_active_row(self) -> None:
        # Two overlapping enables (retried PUT, or two users) — both rows are
        # simultaneously active before disable.
        self.repo.create(self.workflow.id, enabled_by_id=self.user.id, expires_at=_future(30))
        self.repo.create(self.workflow.id, enabled_by_id=self.user.id, expires_at=_future(60))

        self.repo.expire_active_for_workflow(self.workflow.id)

        # The bug: expiring only the newest row left the older one active,
        # so get_active_for_workflow (and ai_workflow_apply.py's own check)
        # would still find a usable session after "disable".
        self.assertIsNone(self.repo.get_active_for_workflow(self.workflow.id))

    def test_expire_active_noop_when_none_active(self) -> None:
        self.repo.expire_active_for_workflow(self.workflow.id)  # must not raise
        self.assertIsNone(self.repo.get_active_for_workflow(self.workflow.id))


if __name__ == "__main__":
    unittest.main()
